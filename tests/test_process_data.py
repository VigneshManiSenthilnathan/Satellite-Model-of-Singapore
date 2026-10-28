"""Panel construction (P1.13, P1.13a, P1.15): helpers, the CSI, and a small fake-registry build."""

import numpy as np
import pandas as pd
import pytest

from data import collect_data, process_data, seasonal
from data.panel import COLUMNS
from data.process_data import (
    _contiguous_tail,
    _regular_until,
    bridge_break,
    build_csi,
    build_panel,
    chain,
    chain_yoy,
    weighted,
)


def _q(values, start="2000Q1"):
    return pd.Series(values, pd.period_range(start, periods=len(values), freq="Q"), dtype=float)


# --------------------------------------------------------------------------- helpers

def test_contiguous_tail_keeps_last_unbroken_run():
    s = _q([1, 2, np.nan, 4, 5, 6])
    assert _contiguous_tail(s).tolist() == [4.0, 5.0, 6.0]
    assert _contiguous_tail(_q([1, 2, 3])).tolist() == [1.0, 2.0, 3.0]
    assert _contiguous_tail(_q([np.nan, np.nan])).empty


def test_regular_until_cuts_sparse_tail():
    s = _q(range(12)).drop(_q(range(12)).index[[7, 9, 11]])     # quarterly to index 6, then every other
    assert _regular_until(s).index[-1] == pd.Period("2001Q3", "Q")
    assert _regular_until(_q([1, 2, 3])).empty                  # no run of 4


def test_chain_qoq_and_saar():
    assert chain(_q([0, 10, -10]), "qoq").round(6).tolist() == [100.0, 110.0, 99.0]
    saar = chain(_q([0, 21.550625]), "qoq_saar")                  # 1.05**4 - 1 = 21.550625%
    assert saar.iloc[-1] == pytest.approx(105.0)
    restarted = chain(_q([5, np.nan, 0, 10]), "qoq")                # restarts after a gap
    assert restarted.tolist() == pytest.approx([100.0, 110.0])
    assert chain(_q([5, 10]), "qoq").iloc[0] == pytest.approx(105.0)  # base 100 precedes the first rate


def test_chain_yoy_anchor_year():
    level = chain_yoy(_q([1, 2, 3, 4, 10, 10, 10, 10, 0]))
    assert level.iloc[:4].tolist() == [100.0] * 4
    assert level.iloc[4:8].tolist() == pytest.approx([110.0] * 4)
    assert level.iloc[8] == pytest.approx(110.0)


def test_weighted_renormalises_and_requires_coverage():
    frame = pd.DataFrame({"a": [1.0, 1.0, np.nan], "b": [3.0, np.nan, np.nan], "c": [np.nan] * 3},
                         index=pd.period_range("2000Q1", periods=3, freq="Q"))
    w = pd.Series({"a": 0.5, "b": 0.3, "c": 0.2})
    out = weighted(frame, w)
    assert out.iloc[0] == pytest.approx((0.5 * 1 + 0.3 * 3) / 0.8)
    assert out.iloc[1] == pytest.approx(1.0)                      # a alone covers 0.5 >= half
    assert len(out) == 2                                          # nothing quoted in the third period
    assert len(weighted(frame, w, min_weight=0.6)) == 1


def test_build_csi_blend_and_spread():
    spread = _q([1.0, 2.0, 3.0, 4.0])
    nim = _q([2.0, 4.0], start="2000Q3")
    blend = build_csi(spread, nim, join=None)
    only = build_csi(spread, nim, variant="spread")
    assert only.tolist() == pytest.approx(spread.tolist())        # spread-only is the spread itself
    assert blend.iloc[:2].tolist() == pytest.approx(spread.iloc[:2].tolist())   # no NIM yet
    z_nim = np.array([-1.0, 1.0]) / np.sqrt(2)                     # z of [2, 4] with sample std
    z_spread = ((spread - spread.mean()) / spread.std()).iloc[2:].to_numpy()
    expected = spread.mean() + spread.std() * (z_spread + z_nim) / 2
    assert blend.iloc[2:].tolist() == pytest.approx(expected.tolist())
    windowed = build_csi(spread, nim, window=("2000Q1", "2000Q2"), variant="spread")
    assert windowed.tolist() == pytest.approx(spread.tolist())    # rescaling undoes the z-score
    with pytest.raises(ValueError):
        build_csi(spread, nim, variant="pca")


def test_build_csi_joins_have_no_step():
    rng = np.random.default_rng(0)
    spread = _q(2 + np.cumsum(rng.normal(0, 0.1, 40)))                       # 2000Q1-2009Q4
    nim = _q(1 + np.cumsum(rng.normal(0, 0.1, 40)) - np.arange(40) * 0.05, start="2005Q1")   # to 2014Q4
    unmatched, matched = build_csi(spread, nim, join=None), build_csi(spread, nim, join=4)
    both = matched.loc["2005Q1":"2009Q4"]
    assert both.tolist() == pytest.approx(unmatched.loc["2005Q1":"2009Q4"].tolist())   # middle unchanged
    zs = (spread - spread.mean()) / spread.std()
    zn = (nim - nim.mean()) / nim.std()
    s = spread.std()
    shift_before = s * ((zs + zn) / 2 - zs).loc["2005Q1":"2005Q4"].mean()
    shift_after = s * ((zs + zn) / 2 - zn).loc["2009Q1":"2009Q4"].mean()
    assert (matched - unmatched).loc[:"2004Q4"].tolist() == pytest.approx([shift_before] * 20)
    assert (matched - unmatched).loc["2010Q1":].tolist() == pytest.approx([shift_after] * 20)


def test_bridge_break_matches_published_yoy():
    old = _q(100 * 1.01 ** np.arange(12))                           # 1% a quarter -> 4.06% y/y
    level = old.copy()
    level.iloc[8:] *= 1.5                                           # base change from 2002Q1
    yoy = _q(np.full(12, 100 * (1.01**4 - 1)))
    bridged, factor = bridge_break(level, yoy, "2002Q1")
    assert factor == pytest.approx(1.5)
    assert bridged.tolist() == pytest.approx((old * 1.5).tolist())


# --------------------------------------------------------------------------- fake-registry build

def _row(ticker, var, freq, sa=True, form="level", role="primary", **extra):
    return {"ticker": ticker, "var": var, "role": role, "freq": freq, "sa": sa, "form": form, **extra}


REGISTRY = {
    "meta": {"default_field": "PX_LAST"},
    "singapore": {
        "gdp": [_row("GDP", "LGDP", "Q")],
        "cpi": [_row("CPI", "LCPI", "M", form="index")],
        "unemployment": [_row("UNR", "UNR", "Q", form="rate")],
        "interest_rate": [_row("SIBOR", "RS", "D", sa=False, form="rate"),
                          _row("SORA", "RS", "D", sa=False, form="rate", role="post"),
                          _row("IMFRATE", "RS", "M", sa=False, form="rate", role="history")],
        "neer": [_row("BIS", "LS", "M", sa=False, form="index"),
                 _row("IMFNEER", "LS", "M", sa=False, form="index", role="history")],
        "csi_lending_rates": [_row("LEND", "CSI", "M", sa=False, form="rate"),
                              _row("LENDH", "CSI", "M", sa=False, form="rate", role="history")],
        "csi_deposit_rates": [_row("DEP", "CSI", "M", sa=False, form="rate"),
                              _row("DEPH", "CSI", "M", sa=False, form="rate", role="history")],
        "csi_net_interest_margin": [
            _row("BANK", "CSI", "Q", sa=False, form="rate", field="T12"),
            _row("BANK", "CSI", "Q", sa=False, form="rate", role="post", field="COMP")],
    },
    "trade": {
        "total_exports_by_partner": [{"ticker": "XUS", "partner": "US"}, {"ticker": "XJP", "partner": "JA"}],
        "imports_by_partner": [{"ticker": "MUS", "partner": "US"}, {"ticker": "MJP", "partner": "JA"}],
    },
    "united_states": [_row("USGDP", "Y_US", "Q"), _row("USCPI", "LCPI_US", "M", form="index"),
                      _row("TBILL", "RS_US", "D", sa=False, form="rate"),
                      _row("EXPINF", "PIE_EXP_US", "M", sa=False, form="rate"),
                      _row("RSTAR", "RR_US_BAR", "Q", sa=False, form="rate")],
    "foreign": {"JP": {"bloc": "JA",
                       "gdp": [{"ticker": "JPGDP", "freq": "Q", "sa": True, "form": "level"}],
                       "cpi": [{"ticker": "JPCPI", "freq": "M", "sa": False, "form": "index"}]}},
}

SPANS = {   # ticker or (ticker, field) -> (start, end) at native frequency; default 1995..2020
    "SIBOR": ("1999-07-01", "2018-12-31"), "SORA": ("2010-01-01", "2020-12-31"),
    "BIS": ("2000-01", "2020-12"), "LEND": ("1998-01", "2018-06"), "DEP": ("1998-01", "2018-06"),
    ("BANK", "T12"): ("2003Q1", "2020Q4"), ("BANK", "COMP"): ("2013Q1", "2020Q4"),
}
SPARSE_FROM = pd.Period("2018Q1", "Q")    # T12 NIM reported half-yearly from here


def fake_load_series(ticker, freq, field="PX_LAST", vintage=None):
    start, end = SPANS.get((ticker, field), SPANS.get(ticker, ("1995-01-01", "2020-12-31")))
    index = pd.period_range(start, end, freq=freq)
    rng = np.random.default_rng(sum(map(ord, ticker + field)))
    t = np.arange(len(index))
    period = {"D": 365, "M": 12, "Q": 4}[freq]
    values = 50 * np.exp(0.002 * t + 0.01 * np.sin(2 * np.pi * t / period)) + rng.normal(0, 0.1, len(t))
    s = pd.Series(values, index, name=ticker)
    if (ticker, field) == ("BANK", "T12"):
        s = s[(s.index < SPARSE_FROM) | (s.index.quarter % 2 == 0)]
    return s


@pytest.fixture
def built(monkeypatch):
    monkeypatch.setattr(process_data, "load_series", fake_load_series)
    monkeypatch.setattr(collect_data, "load_series", fake_load_series)       # build_rs imports it lazily
    monkeypatch.setattr(process_data, "list_vintages", lambda: ["2026-10-27"])
    monkeypatch.setattr(process_data, "adjust", lambda s: seasonal.adjust(s, "stl"))
    return build_panel(registry=REGISTRY)


def test_build_panel_contract(built):
    panel, foreign, lineage, meta = built
    assert list(panel.columns) == COLUMNS
    assert isinstance(panel.index, pd.PeriodIndex) and panel.index.name == "quarter"
    assert panel.index.is_monotonic_increasing and foreign.index.is_monotonic_increasing
    assert meta["vintage"] == "2026-10-27" and meta["provisional"] == ["YF", "LCPIF"]
    assert set(lineage["var"]) >= set(COLUMNS)
    assert lineage.loc[lineage["var"].isin(["YF", "LCPIF"]), "provisional"].all()
    assert meta["seasonal_adjustment"] == {"JPCPI": "stl"}


def test_build_panel_transformations(built):
    panel, *_ = built
    gdp = fake_load_series("GDP", "Q")
    assert panel["LGDP"].dropna().to_numpy() == pytest.approx(100 * np.log(gdp.to_numpy()))
    rr = (fake_load_series("TBILL", "D").groupby(lambda p: p.asfreq("Q")).mean()
          - fake_load_series("EXPINF", "M").groupby(lambda p: p.asfreq("Q")).mean()).dropna()
    rr.index = pd.PeriodIndex(rr.index, freq="Q")
    assert panel["RR_US"].dropna().to_numpy() == pytest.approx(rr.to_numpy())
    assert panel["RS"].first_valid_index() == pd.Period("1995Q1", "Q")      # history splice
    assert panel["RS"].last_valid_index() == pd.Period("2020Q4", "Q")       # post splice
    assert panel["LS"].first_valid_index() == pd.Period("1995Q1", "Q")      # IMF NEER back-cast
    assert panel["CAPREQ_BAR"].loc["2019Q1"] == 10.5


def test_build_panel_nim_continues_past_sparse_tail(built):
    panel, _, lineage, _ = built
    tail = panel["CSI"].loc["2018Q3":"2020Q4"]           # spread ends 2018Q2; NIM only, T12 sparse
    assert tail.notna().all()
    notes = lineage[lineage["source"] == "BANK"]["transform"].tolist()
    assert any("used to 2017Q4" in n for n in notes)
    assert any("company basis" in n and "2018Q1-2020Q4" in n for n in notes)


def test_build_panel_foreign_inputs(built):
    panel, foreign, _, meta = built
    assert {"LGDP_US", "GAP_US", "LCPI_JP", "GAP_JP"} <= set(foreign.columns)
    assert sum(meta["weights"]["omega"].values()) == pytest.approx(1.0, abs=1e-3)
    yf = panel["YF"].dropna()
    assert abs(yf.mean()) < 1.0                          # HP gaps average out near zero
    assert panel["LCPIF"].dropna().index.is_monotonic_increasing
    assert np.isfinite(panel["LCPIF"].dropna()).all()
