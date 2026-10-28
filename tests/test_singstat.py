"""SingStat client and cross-check (P1.8), with a fake HTTP layer -- no network needed."""

import numpy as np
import pandas as pd
import pytest

from data import collect_data, singstat
from data.singstat import compare, crosscheck, fetch_table, parse_period, series


@pytest.mark.parametrize("key, expected", [
    ("1975 1Q", pd.Period("1975Q1", "Q")),
    ("1961 Jan", pd.Period("1961-01", "M")),
    ("2026 Sep", pd.Period("2026-09", "M")),
    ("1999", pd.Period("1999", "Y")),
])
def test_parse_period(key, expected):
    assert parse_period(key) == expected


def test_parse_period_rejects_unknown():
    with pytest.raises(singstat.SingStatError):
        parse_period("Q1 1975")


class FakeHTTP:
    """Serves one table, paginated by data points like the real API (series-major order)."""

    def __init__(self, table, page):
        self.points = [(no, name, key, value) for no, name, cols in table for key, value in cols]
        self.page = page
        self.calls = 0

    def get(self, url, params, headers, timeout):
        self.calls += 1
        chunk = self.points[params["offset"]:params["offset"] + self.page]
        rows = {}
        for no, name, key, value in chunk:
            rows.setdefault(no, {"seriesNo": no, "rowText": name, "uoM": "Index", "columns": []})
            rows[no]["columns"].append({"key": key, "value": value})
        data = {"title": "Fake", "dataLastUpdated": "01/10/2026", "row": list(rows.values())}
        return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: {"Data": data}})()


TABLE = [
    ("1", "All Items", [("2026 Jan", "100"), ("2026 Feb", "101"), ("2026 Mar", "na")]),
    ("2", "Food", [("2026 Jan", "50"), ("2026 Feb", "51"), ("2026 Mar", "52")]),
]


@pytest.fixture
def tmp_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(singstat, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(singstat, "PAGE_POINTS", 2)       # forces a series to split across pages
    return tmp_path


def test_fetch_paginates_and_parses(tmp_cache):
    http = FakeHTTP(TABLE, page=2)
    df = fetch_table("M1", http=http)
    assert http.calls == 4                                 # 6 points in pages of 2, then an empty page
    assert len(df) == 6 and df["series"].nunique() == 2
    assert np.isnan(df.loc[(df["series"] == "All Items") & (df["period"] == "2026-03"), "value"].item())


def test_fetch_caches_by_day_and_reads_vintages(tmp_cache):
    http = FakeHTTP(TABLE, page=2)
    fetch_table("M1", http=http)
    fetch_table("M1", http=http)                           # same day: cache hit
    assert http.calls == 4
    today = pd.Timestamp.today().date().isoformat()
    assert fetch_table("M1", vintage=today).equals(fetch_table("M1", http=http))
    with pytest.raises(FileNotFoundError):
        fetch_table("M1", vintage="2000-01-01")
    with pytest.raises(ValueError, match="cache-only"):
        fetch_table("M1", vintage=today, refresh=True)


def test_series_selects_by_name(tmp_cache):
    fetch_table("M1", http=FakeHTTP(TABLE, page=2))
    food = series("M1", "Food", "M", vintage=pd.Timestamp.today())
    assert food.index.freqstr == "M" and food.tolist() == [50.0, 51.0, 52.0]
    with pytest.raises(KeyError):
        series("M1", "Fuel", "M", vintage=pd.Timestamp.today())


def test_compare_level_and_growth():
    idx = pd.period_range("2026-01", periods=3, freq="M")
    ss = pd.Series([100.0, 110.0, 121.0], idx)
    assert compare(ss * 1.02, ss, "level").round(10).tolist() == [2.0, 2.0, 2.0]
    assert compare(ss * 5, ss, "growth").abs().max() < 1e-12        # different base, same growth
    with pytest.raises(ValueError):
        compare(ss, ss, "ratio")


def test_crosscheck_applies_scale_and_flags(tmp_cache, monkeypatch):
    fetch_table("M1", http=FakeHTTP(TABLE, page=2))
    monkeypatch.setattr(singstat, "series", lambda tid, name, freq, vintage=None: pd.Series(
        [50_000.0, 51_000.0], pd.period_range("2026-01", periods=2, freq="M")))
    bloomberg = {"GOOD Index": [50.0, 51.0], "BAD Index": [60.0, 61.0]}
    monkeypatch.setattr(collect_data, "load_series", lambda t, freq, vintage=None: pd.Series(
        bloomberg[t], pd.period_range("2026-01", periods=2, freq="M")))
    config = {"x": {"id": "M1", "freq": "M", "compare": "level", "scale": 0.001,
                    "series": {"All Items": "GOOD Index", "Food": "BAD Index"}}}
    out = crosscheck(config=config).set_index("ticker")
    assert out.loc["GOOD Index", "flag"] == "ok" and out.loc["BAD Index", "flag"] == "check"
    assert out.loc["GOOD Index", "singstat_uom"] == "Index"


def test_real_config_maps_registry_tickers():
    from data.tickers import series as registry
    known = set(registry()["ticker"])
    for spec in singstat.load_config().values():
        assert set(spec["series"].values()) <= known
