"""The model-ready quarterly panel and the synthetic-data switch (plan tasks P0.7, P1.13).

The panel has one column per domestic observable and per foreign input, on a
quarterly PeriodIndex named ``quarter``. Units follow the README's variable
transformations (``100*ln`` for levels, % or % p.a. for rates).

Synthetic mode (P0.7) is on when ``SMS_SYNTHETIC`` is ``1``/``true``/``yes``
(``run_sms.py --synthetic`` sets it). In synthetic mode ``load_panel`` returns
generated data and ``data.bloomberg`` refuses to open a session, so the whole
pipeline runs without a Terminal.
"""

import os
from pathlib import Path

import pandas as pd

PANEL_PATH = Path(__file__).resolve().parent / "processed" / "panel.parquet"

OBSERVABLES = ["LGDP", "UNR", "LCPI", "RS", "LS", "CSI"]
FOREIGN_INPUTS = ["YF", "LCPIF", "RR_US", "RR_US_BAR"]
OTHER_INPUTS = ["CAPREQ_BAR"]
COLUMNS = OBSERVABLES + FOREIGN_INPUTS + OTHER_INPUTS

SYNTHETIC_ENV = "SMS_SYNTHETIC"


def synthetic_mode():
    """True when the pipeline should run on synthetic data, without Bloomberg."""
    return os.environ.get(SYNTHETIC_ENV, "").strip().lower() in {"1", "true", "yes"}


def load_panel(seed=0):
    """Return the quarterly panel: synthetic in synthetic mode, else the processed parquet."""
    if synthetic_mode():
        from data.synthetic import make_panel

        return make_panel(seed=seed)
    if not PANEL_PATH.exists():
        raise FileNotFoundError(
            f"{PANEL_PATH} not found. Build it with the data pipeline (P1.13), "
            f"or run in synthetic mode (--synthetic or {SYNTHETIC_ENV}=1)."
        )
    return pd.read_parquet(PANEL_PATH)
