"""Data QA report helpers (P1.14): outlier detection and anomaly explanations."""

import numpy as np
import pandas as pd

from data.qa_report import anomalies, changes, csi_stress, explain, interior_gaps, outliers


def _q(values, start="2015Q1", name="X"):
    return pd.Series(values, pd.period_range(start, periods=len(values), freq="Q"), dtype=float, name=name)


def test_changes_annualise_log_levels_only():
    assert changes(_q([400, 401], name="LCPI")).tolist() == [4.0]
    assert changes(_q([2.0, 2.5], name="RS")).tolist() == [0.5]


def test_outliers_flag_large_moves_on_changes():
    rng = np.random.default_rng(0)
    level = _q(np.cumsum(rng.normal(0, 0.1, 40)), name="RS")
    level.iloc[20:] += 10  # one big step
    flagged = outliers(level)
    assert flagged.index.tolist() == [pd.Period("2020Q1", "Q")]
    assert outliers(_q([1.0, 2.0, 3.0])).empty  # too short to judge


def test_gap_series_judged_on_levels():
    gap = _q(np.r_[np.zeros(30) + np.random.default_rng(1).normal(0, 0.1, 30), -5.0], name="GAP_US")
    assert outliers(gap).index[-1] == gap.index[-1]


def test_explain_matches_prefix_and_window():
    assert "COVID" in explain("LGDP", pd.Period("2020Q2", "Q"))
    assert "COVID" in explain("GAP_MX", pd.Period("2020Q2", "Q"))
    assert "Asian" in explain("LGDP_KR", pd.Period("1998Q1", "Q"))
    assert explain("LGDP", pd.Period("2015Q1", "Q")) is None
    assert explain("LCPIF_X", pd.Period("1980Q2", "Q")) is None  # exact name, not a prefix


def test_csi_stress_windows():
    s = _q(np.zeros(60), start="1995Q1")
    s.loc["2008Q3":"2009Q4"] = 1.0
    out = csi_stress({"csi": s}).set_index("episode")["csi"]
    assert out["2008-09 GFC"] == 1.0 and out["1998 Asian crisis"] == 0.0


def test_anomalies_and_gaps():
    frame = pd.DataFrame({"RS": _q(np.r_[np.zeros(20), 10.0, 10.0], name="RS")})
    found = anomalies(frame)
    assert found[["series", "quarter"]].values.tolist() == [["RS", "2020Q1"]]
    assert found["explanation"].isna().all()
    assert interior_gaps(_q([np.nan, 1, np.nan, 2, np.nan])) == 1
