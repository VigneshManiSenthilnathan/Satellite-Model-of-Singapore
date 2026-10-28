"""Quarterly aggregation and splicing (P1.11 / P1.13)."""

import numpy as np
import pandas as pd
import pytest

from data import collect_data
from data.transform import build_rs, splice, to_quarterly


def _monthly(values, start="2020-01"):
    return pd.Series(values, pd.period_range(start, periods=len(values), freq="M"), dtype=float, name="X")


def test_to_quarterly_mean_sum_last():
    s = _monthly([1, 2, 3, 4, 5, 6])
    assert to_quarterly(s, "mean").tolist() == [2.0, 5.0]
    assert to_quarterly(s, "sum").tolist() == [6.0, 15.0]
    assert to_quarterly(s, "last").tolist() == [3.0, 6.0]
    assert str(to_quarterly(s).index[0]) == "2020Q1"


def test_to_quarterly_drops_incomplete_quarters():
    s = _monthly([1, 2, 3, 4])                                   # stops in the first month of Q2
    assert to_quarterly(s).index.astype(str).tolist() == ["2020Q1"]
    assert len(to_quarterly(s, complete_only=False)) == 2
    late_start = _monthly([5, 6, 7, 8, 9], start="2020-02")      # Q1 has only Feb-Mar
    assert to_quarterly(late_start, "sum").index.astype(str).tolist() == ["2020Q2"]
    assert to_quarterly(late_start, "mean").index.astype(str).tolist() == ["2020Q1", "2020Q2"]


def test_to_quarterly_daily():
    days = pd.period_range("2020-01-01", "2020-06-30", freq="D")
    s = pd.Series(np.where(days.month <= 3, 1.0, 3.0), days)
    assert to_quarterly(s).tolist() == [1.0, 3.0]
    assert len(to_quarterly(s.loc[:"2020-05-15"])) == 1           # Q2 incomplete
    assert len(to_quarterly(s.loc[:"2020-06-10"])) == 1           # stops in the last month, 20 days short
    assert len(to_quarterly(s.loc[:"2020-06-26"])) == 2           # last trading days of June count


def test_to_quarterly_rejects_bad_how():
    with pytest.raises(ValueError):
        to_quarterly(_monthly([1, 2, 3]), "median")


def _q(values, start):
    return pd.Series(values, pd.period_range(start, periods=len(values), freq="Q"), dtype=float)


def test_splice_level_after_and_before():
    core = _q([5, 5, 5, 5], "2000Q1").rename("core")
    after = _q([4, 4, 4, 4], "2000Q3").rename("after")            # 1pp below core on the overlap
    out, meta = splice(core, after, "after")
    assert meta["shift"] == 1.0 and meta["overlap_n"] == 2 and meta["extended"] == "2001Q1-2001Q2"
    assert out.tolist() == [5, 5, 5, 5, 5, 5] and out.name == "core"
    before = _q([7, 7, 7], "1999Q3").rename("before")
    out, meta = splice(core, before, "before")
    assert meta["shift"] == -2.0 and out.index[0] == pd.Period("1999Q3", "Q") and (out == 5).all()


def test_splice_ratio():
    core = _q([110, 121], "2000Q1")
    other = _q([10, 11, 12.1], "1999Q4")                          # same growth, base 10x smaller
    out, meta = splice(core, other, "before", how="ratio")
    assert meta["shift"] == pytest.approx(10.0)
    assert out.tolist() == pytest.approx([100, 110, 121])


def test_splice_join_window_uses_periods_nearest_the_join():
    core = _q([10, 20, 40], "2001Q1")                            # drifts away from `other` over time
    other = _q([4, 5, 5, 5, 5], "2000Q3")                       # overlap 2001Q1-Q3: ratios 2, 4, 8
    before, meta = splice(core, other, "before", how="ratio", join=1)
    assert meta["shift"] == pytest.approx(2.0) and meta["overlap"] == "2001Q1-2001Q1"
    assert before.loc["2000Q4"] == pytest.approx(10.0)            # 5 * 2 meets core's 10 smoothly
    _, full = splice(core, other, "before", how="ratio")
    assert full["shift"] != pytest.approx(2.0)
    after, meta = splice(_q([1, 2, 3, 4], "2000Q1"), _q([0, 1, 5, 9], "2000Q2"), "after", join=2)
    assert meta["overlap"] == "2000Q3-2000Q4" and meta["shift"] == pytest.approx(0.5)   # gaps 2, -1
    assert after.loc["2001Q1"] == pytest.approx(9.5)


def test_splice_errors():
    core = _q([1, 2], "2000Q1")
    with pytest.raises(ValueError, match="overlap"):
        splice(core, _q([1], "1990Q1"), "before")
    with pytest.raises(ValueError):
        splice(core, core, "middle")
    with pytest.raises(ValueError):
        splice(core, core, "after", how="log")


def test_build_rs_uses_registry_roles(monkeypatch):
    registry = {"singapore": {"interest_rate": [
        {"ticker": "CORE Index", "var": "RS", "role": "primary", "freq": "Q"},
        {"ticker": "POST Index", "var": "RS", "role": "post", "freq": "Q"},
        {"ticker": "HIST Index", "var": "RS", "role": "history", "freq": "Q"},
    ]}}
    data = {"CORE Index": _q([3, 3, 3], "2000Q1"), "POST Index": _q([2.5, 2.5, 2.5], "2000Q3"),
            "HIST Index": _q([2, 2, 2], "1999Q3")}
    monkeypatch.setattr(collect_data, "load_series", lambda t, freq, vintage=None: data[t].rename(t))
    rs, meta = build_rs(registry=registry)
    assert rs.name == "RS" and (rs == 3).all()
    assert rs.index[0] == pd.Period("1999Q3", "Q") and rs.index[-1] == pd.Period("2001Q1", "Q")
    assert [m["shift"] for m in meta] == [1.0, 0.5]
