"""Quarterly CAPREQ_BAR from the capital-requirement timeline, config/capreq.yaml (plan task P1.7).

Each quarter takes the requirement in force on its last day. Quarters before
the first step are NaN (no sourced value before 1992).

Measures:
    tier1_plus_ccb  Tier 1 minimum + capital conservation buffer (CAPREQ_BAR, default)
    tier1_min       Tier 1 minimum only (robustness variant)

Usage:
    from data.capreq import capreq_series
    capreq_series("1995Q1", "2025Q4")            # quarterly PeriodIndex, % of RWA
"""

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

CAPREQ_PATH = Path(__file__).resolve().parent.parent / "config" / "capreq.yaml"
MEASURES = {"tier1_plus_ccb", "tier1_min"}


def load_steps(path=CAPREQ_PATH):
    """The timeline as a DataFrame indexed by effective date, sorted, with ccb defaulting to 0."""
    with open(path, encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    steps = pd.DataFrame(spec["steps"])
    steps["from"] = pd.to_datetime(steps["from"])
    steps["ccb"] = steps.get("ccb", 0.0)
    steps["ccb"] = steps["ccb"].fillna(0.0)
    steps["tier1_plus_ccb"] = steps["tier1_min"] + steps["ccb"]
    steps = steps.set_index("from").sort_index()
    if not steps.index.is_unique:
        raise ValueError(f"{path}: duplicate step dates")
    return steps, spec.get("measure", "tier1_plus_ccb")


def capreq_series(start, end, measure=None, path=CAPREQ_PATH):
    """Quarterly requirement (% of RWA) on a PeriodIndex named `quarter`."""
    steps, default = load_steps(path)
    measure = measure or default
    if measure not in MEASURES:
        raise ValueError(f"measure must be one of {sorted(MEASURES)}, got {measure!r}")
    index = pd.period_range(start, end, freq="Q", name="quarter")
    quarter_ends = index.to_timestamp(how="end").normalize()
    pos = steps.index.searchsorted(quarter_ends, side="right") - 1      # last step on or before quarter end
    values = np.where(pos >= 0, steps[measure].to_numpy()[np.maximum(pos, 0)], np.nan)
    return pd.Series(values, index=index, name="CAPREQ_BAR")
