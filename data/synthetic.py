"""Synthetic quarterly panel for running the pipeline without Bloomberg (plan task P0.7).

Each series is a seeded AR(1) or random-walk stand-in with roughly
Singapore-like levels and volatilities. Same columns, index and units as the
real panel (see data.panel). It is a placeholder: once the model core exists
(Phase 2), replace it with data simulated from the solved model so tests can
check that estimation recovers known parameters.

Usage:
    from data.synthetic import make_panel
    panel = make_panel(seed=0)
"""

import numpy as np
import pandas as pd

from data.panel import COLUMNS


def _ar1(rng, n, mean, rho, sd):
    x = np.empty(n)
    x[0] = mean + rng.normal(0, sd / np.sqrt(1 - rho**2))
    for t in range(1, n):
        x[t] = mean + rho * (x[t - 1] - mean) + rng.normal(0, sd)
    return x


def _log_level(start_level, growth_pa):
    # 100*ln level built from annualised % growth rates (PIE-style: level += growth/4).
    return 100 * np.log(start_level) + np.cumsum(growth_pa / 4)


def make_panel(start="1995Q1", end="2025Q4", seed=0):
    """Generate the synthetic panel. Same seed -> identical frame."""
    rng = np.random.default_rng(seed)
    index = pd.period_range(start, end, freq="Q", name="quarter")
    n = len(index)

    gdp_growth = _ar1(rng, n, mean=2.5, rho=0.3, sd=3.0)   # q/q SAAR, %
    pie = _ar1(rng, n, mean=2.0, rho=0.6, sd=1.5)          # CPI inflation, % p.a.
    dot_ls = _ar1(rng, n, mean=1.0, rho=0.7, sd=2.0)       # S$NEER appreciation, % p.a.
    pief = _ar1(rng, n, mean=2.0, rho=0.7, sd=1.0)         # foreign inflation, % p.a.
    rr_us_bar = 0.5 + np.cumsum(rng.normal(0, 0.05, n))    # US r*, slow random walk

    panel = pd.DataFrame(
        {
            "LGDP": _log_level(60_000, gdp_growth),              # S$ million, chained, per quarter
            "UNR": np.clip(_ar1(rng, n, mean=3.0, rho=0.9, sd=0.2), 0.5, None),
            "LCPI": _log_level(100, pie),
            "RS": np.clip(_ar1(rng, n, mean=2.0, rho=0.9, sd=0.4), 0.0, None),
            "LS": _log_level(100, dot_ls),
            "CSI": _ar1(rng, n, mean=2.0, rho=0.9, sd=0.15),
            "YF": _ar1(rng, n, mean=0.0, rho=0.85, sd=0.5),
            "LCPIF": _log_level(100, pief),
            "RR_US": rr_us_bar + _ar1(rng, n, mean=0.0, rho=0.8, sd=0.5),
            "RR_US_BAR": rr_us_bar,
            "CAPREQ_BAR": np.where(index < pd.Period("2013Q1", "Q"), 6.0, 6.5),  # one regulatory step
        },
        index=index,
    )
    return panel[COLUMNS]
