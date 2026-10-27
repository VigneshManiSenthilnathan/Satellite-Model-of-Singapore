"""collect_data (P1.6b): pull list, manifest and registry re-verification, with fake bdh/bdp."""

import pandas as pd
import pytest

from data import collect_data
from data.bloomberg import BloombergError, BloombergSecurityError, BloombergSessionError
from data.collect_data import collect, pull_list, verify

REGISTRY = {
    "meta": {"default_field": "PX_LAST"},
    "singapore": {
        "gdp": [{"ticker": "GDP Index", "var": "LGDP", "freq": "Q", "span": "1980Q1-2026Q2"}],
        "cpi": [{"ticker": "CPI Index", "var": "LCPI", "freq": "M", "span": "1980Q1-2026Q3"}],
        "consensus": [{"template": "ECGDSG {yy} Index", "var": "none", "role": "reference"}],
    },
    "trade": {"nodx_by_partner": [{"ticker": "NODX Index", "partner": "US", "span": "1980Q1-2026Q3"}]},
    "consensus": {"templates": {"gdp": "ECGD{cc} {yy} Index", "cpi": "ECPI{cc} {yy} Index",
                                "policy_rate": "ECPO{cc} {yy} Index"},
                  "countries": ["US", "SG"], "policy_rate_countries": ["US"]},
}


def test_pull_list_frequencies_and_consensus():
    items = pull_list([2026], registry=REGISTRY)
    freq = dict(zip(items["ticker"], items["freq"], strict=True))
    assert freq["GDP Index"] == "Q" and freq["CPI Index"] == "M"
    assert freq["NODX Index"] == "M"                                   # trade default
    consensus = items[items["section"] == "consensus"]
    # 2 countries x (gdp, cpi) + US policy rate; ECGDSG 26 appears twice in the registry but is pulled once
    assert sorted(consensus["ticker"]) == ["ECGDSG 26 Index", "ECGDUS 26 Index", "ECPISG 26 Index",
                                           "ECPIUS 26 Index", "ECPOUS 26 Index"]
    assert set(consensus["freq"]) == {"M"} and set(consensus["field"]) == {"PX_LAST"}


def test_real_registry_pull_list():
    items = pull_list([2026, 2027])
    assert not items.duplicated(["ticker", "field", "freq"]).any()
    assert set(items["freq"]) <= set(collect_data.PERIODICITY)
    assert (items["section"] == "consensus").sum() == 2 * (21 + 21 + 1) + 2   # + ECCXSG for two years


def _fake_bdh(data):
    def bdh(ticker, field, start, periodicity, periodicityAdjustment, refresh):
        result = data[ticker]
        if isinstance(result, Exception):
            raise result
        return pd.DataFrame({"date": pd.to_datetime(result), "ticker": ticker, "field": field, "value": 1.0})
    return bdh


@pytest.fixture
def items():
    return pull_list([2026], registry=REGISTRY)


def test_collect_records_spans_and_errors(monkeypatch, items):
    data = {t: ["1980-03-31", "2026-06-30"] for t in items["ticker"]}
    data["CPI Index"] = ["1980-01-31", "2026-09-30"]
    data["NODX Index"] = []
    data["ECGDUS 26 Index"] = BloombergSecurityError("ECGDUS 26 Index: Unknown/Invalid security")
    data["ECPIUS 26 Index"] = BloombergError("responseError")
    monkeypatch.setattr(collect_data, "bdh", _fake_bdh(data))

    manifest = collect(items, progress=None).set_index("ticker")
    assert manifest.loc["GDP Index", "span_pulled"] == "1980Q1-2026Q2"
    assert manifest.loc["CPI Index", "periodicity"] == "MONTHLY"
    assert manifest.loc["NODX Index", "result"] == "empty"
    assert manifest.loc["ECGDUS 26 Index", "result"] == "bad_ticker"
    assert manifest.loc["ECPIUS 26 Index", "result"] == "error"


def test_collect_stops_when_session_stays_down(monkeypatch, items):
    data = {t: BloombergSessionError("dropped") for t in items["ticker"]}
    monkeypatch.setattr(collect_data, "bdh", _fake_bdh(data))
    with pytest.raises(BloombergSessionError):
        collect(items, progress=None)


def _manifest(rows):
    cols = ["ticker", "field", "span", "span_pulled", "result", "message"]
    return pd.DataFrame([dict(zip(cols, r, strict=True)) for r in rows])


def test_verify_flags_problems_and_extensions():
    manifest = _manifest([
        ("OK Index",      "PX_LAST", "1980Q1-2026Q2", "1980Q1-2026Q2", "ok", ""),
        ("MOVED Index",   "PX_LAST", "1980Q1-2026Q2", "1985Q1-2026Q2", "ok", ""),
        ("STOP Index",    "PX_LAST", "1980Q1-2026Q2", "1980Q1-2024Q4", "ok", ""),
        ("NEW Index",     "PX_LAST", "1980Q1-2026Q2", "1980Q1-2026Q3", "ok", ""),
        ("EMPTY Index",   "PX_LAST", "1980Q1-2026Q2", None,            "empty", ""),
        ("GHOST Index",   "PX_LAST", None,            None,            "bad_ticker", "unknown security"),
        ("CONS 26 Index", "PX_LAST", None,            "2025Q1-2026Q3", "ok", ""),
    ])
    names = {t: "name" for t in manifest["ticker"] if t != "GHOST Index"}
    found = verify(manifest, names=names)
    checks = {(r.ticker, r.check, r.severity) for r in found.itertuples()}
    assert checks == {
        ("MOVED Index", "span_start", "problem"),
        ("STOP Index", "span_end", "problem"),
        ("NEW Index", "span_end", "info"),
        ("EMPTY Index", "pull", "problem"),
        ("GHOST Index", "resolve", "problem"),
        ("GHOST Index", "pull", "problem"),
    }


def test_main_refuses_in_synthetic_mode(capsys):
    assert collect_data.main([]) == 1
    assert "needs Bloomberg" in capsys.readouterr().err


@pytest.mark.bloomberg
def test_live_collect_one_series():
    items = pull_list([2026]).query("ticker == 'SGDSTOTL Index'")
    manifest = collect(items, progress=None)
    assert manifest["result"].item() == "ok"
    assert manifest["span_pulled"].item().startswith("1980Q1")
