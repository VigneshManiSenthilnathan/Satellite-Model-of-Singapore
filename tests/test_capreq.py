"""Capital-requirement timeline (P1.7) against the committed config/capreq.yaml."""

import numpy as np
import pytest

from data.capreq import capreq_series, load_steps


def test_every_step_is_sourced_and_ordered():
    steps, measure = load_steps()
    assert measure == "tier1_plus_ccb"
    assert steps["source"].notna().all() and steps["url"].str.startswith("https://www.mas.gov.sg").all()
    assert steps.index.is_monotonic_increasing
    assert (steps["tier1_min"] <= steps["total_min"]).all()


def test_quarterly_values_at_known_dates():
    s = capreq_series("1991Q4", "2020Q1")
    assert np.isnan(s["1991Q4"])                     # nothing sourced before 1992
    assert s["1992Q1"] == 12.0
    assert s["1998Q3"] == 12.0 and s["1998Q4"] == 10.0
    assert s["2000Q2"] == 10.0 and s["2000Q3"] == 8.0   # effective 30 Sep = last day of Q3
    assert s["2004Q2"] == 7.0                        # effective 30 Jun
    assert s["2007Q1"] == 6.0
    assert s["2013Q1"] == 6.0 and s["2014Q1"] == 7.0 and s["2015Q1"] == 8.0
    assert s["2016Q1"] == 8.625 and s["2019Q1"] == 10.5 and s["2020Q1"] == 10.5


def test_minimum_only_variant():
    s = capreq_series("2015Q4", "2019Q4", measure="tier1_min")
    assert (s == 8.0).all()


def test_bad_measure():
    with pytest.raises(ValueError, match="measure"):
        capreq_series("2000Q1", "2000Q4", measure="total")
