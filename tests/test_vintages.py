"""Vintage reads from the Bloomberg cache (P1.3). Uses a temporary cache; no Terminal needed."""

import datetime as dt
from types import SimpleNamespace

import pandas as pd
import pytest

from data import bloomberg
from data.bloomberg import _bdh_spec, _cache_write, _request_key, bdh, bdp, list_vintages


@pytest.fixture
def cache(monkeypatch, tmp_path):
    """Empty temp cache; returns put(vintage, value) which caches an open-ended pull made on that day."""
    monkeypatch.setattr(bloomberg, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(bloomberg, "_blpapi", lambda: SimpleNamespace(__version__="test"))

    def on(day):
        class Day(dt.date):
            @classmethod
            def today(cls):
                return day
        monkeypatch.setattr(bloomberg, "dt", SimpleNamespace(date=Day, datetime=dt.datetime))

    def put(vintage, value, end=None):
        on(dt.date.fromisoformat(vintage))
        spec = _bdh_spec(["X Index"], ["PX_LAST"], "2000-01-01", end, "MONTHLY", None, None, {})
        df = pd.DataFrame({"date": pd.to_datetime(["2000-01-31"]), "ticker": "X Index",
                           "field": "PX_LAST", "value": [value]})
        _cache_write("bdh", _request_key(spec), df, spec, [])
        ref = pd.DataFrame({"ticker": ["X Index"], "field": ["NAME"], "value": [f"name {value}"]})
        ref_spec = {"tickers": ["X Index"], "fields": ["NAME"], "overrides": {}}
        _cache_write("bdp", _request_key(ref_spec), ref.astype("string"), ref_spec, [])

    put.today = on
    return put


def _read(vintage, end=None):
    return bdh("X Index", "PX_LAST", "2000-01-01", end=end, periodicity="MONTHLY", vintage=vintage)


def test_open_ended_pull_read_back_on_a_later_day(cache):
    cache("2026-10-27", 1.0)
    cache("2026-11-03", 2.0)
    cache.today(dt.date(2026, 12, 1))                       # neither key matches "today" any more
    assert list_vintages() == ["2026-10-27", "2026-11-03"]
    assert _read("2026-10-27")["value"].item() == 1.0
    assert _read("2026-11-03")["value"].item() == 2.0


def test_open_ended_pull_needs_its_own_day(cache):
    cache("2026-10-27", 1.0)
    with pytest.raises(FileNotFoundError, match="2026-10-30"):
        _read("2026-10-30")                                  # end=None means end=vintage date


def test_fixed_end_request_uses_newest_vintage_at_or_before(cache):
    cache("2026-10-27", 1.0, end="2025-12-31")
    cache("2026-11-03", 2.0, end="2025-12-31")
    assert _read("2026-10-30", end="2025-12-31")["value"].item() == 1.0
    assert _read("2026-11-03", end="2025-12-31")["value"].item() == 2.0
    with pytest.raises(FileNotFoundError):
        _read("2026-10-01", end="2025-12-31")


def test_bdp_vintage(cache):
    cache("2026-10-27", 1.0)
    cache("2026-11-03", 2.0)
    assert bdp("X Index", "NAME", vintage="2026-10-31")["value"].item() == "name 1.0"
    assert bdp("X Index", "NAME", vintage="2026-11-03")["value"].item() == "name 2.0"


def test_vintage_and_refresh_conflict():
    with pytest.raises(ValueError, match="cache-only"):
        bdh("X Index", "PX_LAST", "2000-01-01", vintage="2026-10-27", refresh=True)
    with pytest.raises(ValueError, match="cache-only"):
        bdp("X Index", "NAME", vintage="2026-10-27", refresh=True)


def test_vintage_read_never_opens_a_session(cache, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("vintage read tried to reach Bloomberg")
    monkeypatch.setattr(bloomberg, "_with_session", boom)
    with pytest.raises(FileNotFoundError):
        _read("2026-10-27")
