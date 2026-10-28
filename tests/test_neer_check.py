"""S$NEER validation (P1.12) on a small fake registry -- no Bloomberg needed."""

import numpy as np
import pandas as pd
import pytest

from data import neer_check


def _fx(partner):
    return {"ticker": f"SGD{partner}A Curncy", "var": "LS", "role": "crosscheck",
            "partner": partner, "freq": "M"}


REGISTRY = {
    "singapore": {
        "neer": [{"ticker": "BIS Index", "var": "LS", "role": "primary", "freq": "M"},
                 {"ticker": "ALT Index", "var": "LS", "role": "crosscheck", "freq": "M"}],
        "neer_bilateral": [_fx("AA"), _fx("BB")],
    },
    "trade": {
        "total_exports_by_partner": [{"ticker": "XAA Index", "partner": "AA"},
                                     {"ticker": "XBB Index", "partner": "BB"}],
        "imports_by_partner": [{"ticker": "MAA Index", "partner": "AA"},
                               {"ticker": "MBB Index", "partner": "BB"}],
    },
}

MONTHS = pd.period_range("2003-01", "2025-12", freq="M")


@pytest.fixture
def fake_data(monkeypatch):
    n = len(MONTHS)
    data = {
        "XAA Index": np.full(n, 3.0), "MAA Index": np.full(n, 3.0),     # AA: 75% of trade
        "XBB Index": np.full(n, 1.0), "MBB Index": np.full(n, 1.0),     # BB: 25%
        "SGDAAA Curncy": np.exp(0.01 * np.arange(n)),                   # S$ +1% a month vs AA
        "SGDBBA Curncy": np.exp(-0.01 * np.arange(n)),                  # S$ -1% a month vs BB
        "BIS Index": np.exp(0.005 * np.arange(n)),
        "ALT Index": np.exp(0.005 * np.arange(n)),
    }

    def load(ticker, freq, vintage=None):
        return pd.Series(data[ticker], MONTHS, name=ticker)
    monkeypatch.setattr(neer_check, "load_series", load)


def test_trade_weights(fake_data):
    w = neer_check.trade_weights(registry=REGISTRY)
    assert w.to_dict() == pytest.approx({"AA": 0.75, "BB": 0.25})


def test_twi_is_weighted_growth(fake_data):
    index = neer_check.twi(registry=REGISTRY)
    assert index.diff().dropna().to_numpy() == pytest.approx(0.75 * 1 - 0.25 * 1)   # 0.5 log-pp a month


def test_compare_proxies(fake_data):
    levels = neer_check.proxies(registry=REGISTRY)
    assert set(levels.columns) == {"BIS Index", "ALT Index", "TWI"}
    out = neer_check.compare_proxies(levels, primary="BIS Index").set_index("proxy")
    assert out.loc["ALT Index", "te_12m_pp"] == pytest.approx(0, abs=1e-9)
    assert out.loc["TWI", "mean_gap_12m_pp"] == pytest.approx(0, abs=1e-9)      # both grow 0.5 a month


DECISIONS = pd.DataFrame([
    {"date": "2010-01-01", "slope_change": "increase", "slope_stance": "appreciation", "centre": "unchanged",
     "confidence": "high"},
    {"date": "2010-07-01", "slope_change": "unchanged", "slope_stance": "appreciation", "centre": "unchanged",
     "confidence": "high"},                                   # unchanged review: extends the episode
    {"date": "2011-07-01", "slope_change": "set_zero", "slope_stance": "zero", "centre": "down",
     "confidence": "high"},
])


def test_episodes_merge_unchanged_reviews():
    eps = neer_check.episodes(DECISIONS, end="2012-07-01")
    assert eps["stance"].tolist() == ["appreciation", "zero"]
    assert str(eps["end"].iloc[0].date()) == "2011-07-01"


def test_episode_slopes_and_agreement():
    months = pd.period_range("2010-01", "2012-07", freq="M")
    t = np.arange(len(months))
    up_then_flat = np.where(months < pd.Period("2011-07", "M"), 2.0 / 12 * t, 2.0 / 12 * 18)
    levels = pd.DataFrame({"good": up_then_flat, "bad": -up_then_flat}, index=months)
    out = neer_check.episode_slopes(levels, neer_check.episodes(DECISIONS, end="2012-07-01"))
    assert out["good"].iloc[0] == pytest.approx(2.0)                       # % p.a.
    assert out["good_agrees"].tolist() == [True, True]
    assert out["bad_agrees"].tolist() == [False, True]       # falling NEER in an appreciation episode


def test_real_policy_file_loads():
    d = neer_check.load_decisions()
    assert set(d["slope_stance"]) <= {"appreciation", "zero", "depreciation"}
    assert pd.to_datetime(d["date"]).is_monotonic_increasing
    assert d.loc[d["confidence"] == "high", "url"].str.startswith("https://www.mas.gov.sg").all()
