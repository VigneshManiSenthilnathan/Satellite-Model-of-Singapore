"""Seasonal adjustment of NSA series (plan task P1.10).

X-13ARIMA-SEATS through statsmodels when the Census binary is present
(tools/x13as/x13as.exe, git-ignored; or set X13PATH), otherwise STL. Both work
on logs, i.e. multiplicative adjustment, which suits price indices and GDP
levels. ``adjust`` returns the method actually used so lineage (P1.15) can
record it.

Each X-13 call has a time limit (decision Q9): if x13as.exe runs longer than
X13_TIMEOUT_S it is killed and the series falls back to STL, reported as
"stl (x13 timed out)". An X-13 error falls back the same way ("stl (x13
error)"). Every call runs in its own temporary directory, so X-13's output
files are always removed.

Which series are adjusted: ``sa_candidates()`` -- the primary registry GDP and
CPI series (vars Y_* / LCPI_*) that are NSA, i.e. exactly what P1.13 adjusts.
Series given as growth rates (China CPI m/m, Indonesia GDP y/y) are adjusted
after P1.13 chains them into levels. Rates, exchange rates and trade flows are
not adjusted (trade weights use annual sums).

Usage:
    from data.seasonal import adjust
    sa, method = adjust(cpi_nsa)          # PeriodIndex, monthly or quarterly
"""

import io
import os
import subprocess
import tempfile
import warnings
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import statsmodels.tsa.x13 as sm_x13
from statsmodels.tsa.seasonal import STL
from statsmodels.tsa.x13 import X13Error, x13_arima_analysis

X13_PATH = Path(__file__).resolve().parent.parent / "tools" / "x13as" / "x13as.exe"
X13_TIMEOUT_S = 300     # slowest series on the 2026-10-27 vintage took 74 s (Malaysia CPI)
PERIODS = {"M": 12, "Q": 4}
METHODS = {"auto", "x13", "stl"}


class X13Timeout(X13Error):
    """x13as.exe exceeded X13_TIMEOUT_S and was killed."""


class _TimedProcess:
    """Stand-in for the Popen that statsmodels waits on: wait() has a time limit and kills x13as on expiry.

    statsmodels calls p.wait() with no timeout, so a stuck x13as.exe would block forever and
    outlive the Python process. x13as is launched directly (no shell), so kill() ends it.
    """

    def __init__(self, proc, timeout):
        self.proc, self.timeout, self.stdout = proc, timeout, None

    def wait(self):
        try:
            out, _ = self.proc.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.communicate()
            raise X13Timeout(f"x13as did not finish within {self.timeout:.0f} s and was killed") from None
        self.stdout = io.BytesIO(out or b"")
        return self.proc.returncode


def x13_binary():
    """Path to the X-13 binary, or None. X13PATH overrides the bundled tools/ location."""
    path = Path(os.environ.get("X13PATH", X13_PATH))
    if path.is_dir():
        path = path / "x13as.exe"
    return path if path.exists() else None


def _period(series):
    freq = series.index.freqstr[0]
    if freq not in PERIODS:
        raise ValueError("seasonal adjustment needs a monthly or quarterly PeriodIndex, "
                         f"got {series.index.freqstr}")
    return PERIODS[freq]


def _x13(log_series, binary, timeout=None):
    endog = pd.Series(log_series.to_numpy(), index=log_series.index.to_timestamp(how="start"))
    timeout = X13_TIMEOUT_S if timeout is None else timeout
    launch = sm_x13.run_spec

    def run_spec(*args, **kwargs):
        return _TimedProcess(launch(*args, **kwargs), timeout)

    with (warnings.catch_warnings(),
          tempfile.TemporaryDirectory(prefix="x13_", ignore_cleanup_errors=True) as tmp,
          mock.patch.object(sm_x13, "run_spec", run_spec)):
        warnings.simplefilter("ignore")      # X-13 echoes its own diagnostics as warnings
        result = x13_arima_analysis(endog, x12path=str(binary), log=False, outlier=True,
                                    trading=False, tempdir=tmp)
    return pd.Series(result.seasadj.to_numpy(), index=log_series.index)


def _stl(log_series):
    result = STL(log_series.to_numpy(), period=_period(log_series), robust=True).fit()
    return log_series - result.seasonal


def adjust(series, method="auto"):
    """Seasonally adjust a positive series. Returns (adjusted series, method used).

    The method is 'x13' or 'stl', or with method='auto' 'stl (x13 timed out)' / 'stl (x13 error)'
    when X-13 was tried and failed. Leading and trailing NaNs are kept as NaN; interior gaps
    raise ValueError.
    """
    if method not in METHODS:
        raise ValueError(f"method must be one of {sorted(METHODS)}, got {method!r}")
    _period(series)
    data = series.loc[series.first_valid_index():series.last_valid_index()]
    if data.isna().any():
        raise ValueError(f"{series.name}: interior gaps; fill or splice before seasonal adjustment")
    if (data <= 0).any():
        raise ValueError(f"{series.name}: multiplicative adjustment needs positive values")
    logged = np.log(data)

    binary = x13_binary()
    if method == "x13" and binary is None:
        raise FileNotFoundError(f"X-13 binary not found at {X13_PATH} (or X13PATH)")
    used = "x13" if method in {"auto", "x13"} and binary is not None else "stl"
    if used == "x13":
        try:
            adjusted = _x13(logged, binary)
        except X13Error as exc:
            if method == "x13":
                raise
            reason = "timed out" if isinstance(exc, X13Timeout) else "error"
            adjusted, used = _stl(logged), f"stl (x13 {reason})"
    else:
        adjusted = _stl(logged)
    return np.exp(adjusted).reindex(series.index).rename(series.name), used


def sa_candidates(registry=None):
    """Registry rows that P1.13 seasonally adjusts: primary NSA GDP/CPI series (growth forms once chained)."""
    from data.tickers import series as registry_series

    df = registry_series(registry)
    is_macro = df["var"].fillna("").str.match(r"^(Y|LCPI)_")
    return df[is_macro & (df["sa"] == False) & (df["role"] == "primary")].reset_index(drop=True)  # noqa: E712
