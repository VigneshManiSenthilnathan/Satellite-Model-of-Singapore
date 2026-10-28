"""Seasonal adjustment (P1.10). X-13 tests are skipped where the Census binary is absent (e.g. CI)."""

import subprocess
import sys

import numpy as np
import pandas as pd
import pytest
from statsmodels.tsa.x13 import X13Error

from data import seasonal
from data.seasonal import X13Timeout, _TimedProcess, adjust, sa_candidates, x13_binary

needs_x13 = pytest.mark.skipif(x13_binary() is None, reason="X-13 binary not installed in tools/x13as")


def _seasonal_series(freq="M", n=240, seed=0):
    rng = np.random.default_rng(seed)
    index = pd.period_range("2000-01" if freq == "M" else "2000Q1", periods=n, freq=freq)
    period = 12 if freq == "M" else 4
    pattern = 2.0 * np.sin(2 * np.pi * np.arange(n) / period)          # +/-2% seasonal swing
    log_level = 4.6 + 0.002 * np.arange(n) + pattern / 100 + rng.normal(0, 0.001, n)
    return pd.Series(np.exp(log_level), index=index, name="X")


def _seasonal_range(series):
    growth = np.log(series).diff().dropna()
    by_season = growth.groupby(growth.index.month if growth.index.freqstr[0] == "M" else growth.index.quarter)
    return 100 * (by_season.mean().max() - by_season.mean().min())


@pytest.mark.parametrize("method", ["stl", pytest.param("x13", marks=needs_x13)])
@pytest.mark.parametrize("freq", ["M", "Q"])
def test_removes_seasonality(method, freq):
    raw = _seasonal_series(freq)
    sa, used = adjust(raw, method)
    assert used == method
    assert _seasonal_range(sa) < 0.2 * _seasonal_range(raw)
    assert abs(np.log(sa.iloc[-1] / sa.iloc[0]) - np.log(raw.iloc[-1] / raw.iloc[0])) < 0.05   # trend kept


def test_edge_nans_kept_interior_gap_rejected():
    raw = _seasonal_series()
    raw.iloc[:3] = np.nan
    sa, _ = adjust(raw, "stl")
    assert sa.iloc[:3].isna().all() and sa.iloc[3:].notna().all()
    raw.iloc[100] = np.nan
    with pytest.raises(ValueError, match="interior gaps"):
        adjust(raw, "stl")


def test_rejects_bad_input():
    raw = _seasonal_series()
    with pytest.raises(ValueError, match="positive"):
        adjust(raw - 200, "stl")
    with pytest.raises(ValueError, match="monthly or quarterly"):
        adjust(pd.Series(1.0, pd.period_range("2000", periods=30, freq="Y")), "stl")
    with pytest.raises(ValueError, match="method"):
        adjust(raw, "seats")


def test_missing_binary_falls_back_to_stl(monkeypatch):
    monkeypatch.setattr(seasonal, "x13_binary", lambda: None)
    assert adjust(_seasonal_series(), "auto")[1] == "stl"
    with pytest.raises(FileNotFoundError):
        adjust(_seasonal_series(), "x13")


def test_timed_process_kills_on_timeout():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    with pytest.raises(X13Timeout):
        _TimedProcess(proc, timeout=0.5).wait()
    assert proc.poll() is not None                            # child really ended


def test_timed_process_passes_stdout_through():
    proc = subprocess.Popen([sys.executable, "-c", "print('hello')"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    p = _TimedProcess(proc, timeout=30)
    assert p.wait() == 0 and p.stdout.read().strip() == b"hello"


def test_x13_error_falls_back_to_stl(monkeypatch):
    def fail(*args, **kwargs):
        raise X13Error("boom")

    monkeypatch.setattr(seasonal, "x13_binary", lambda: "x13as.exe")
    monkeypatch.setattr(seasonal, "_x13", fail)
    sa, used = adjust(_seasonal_series(), "auto")
    assert used == "stl (x13 error)" and sa.notna().all()
    with pytest.raises(X13Error):
        adjust(_seasonal_series(), "x13")


@needs_x13
def test_x13_timeout_kills_binary_and_falls_back(monkeypatch):
    launched = []

    class Recording(_TimedProcess):
        def __init__(self, proc, timeout):
            launched.append(proc)
            super().__init__(proc, timeout)

    monkeypatch.setattr(seasonal, "X13_TIMEOUT_S", 0.01)
    monkeypatch.setattr(seasonal, "_TimedProcess", Recording)
    sa, used = adjust(_seasonal_series(n=480), "auto")
    assert used == "stl (x13 timed out)" and sa.notna().all()
    assert len(launched) == 1 and launched[0].poll() is not None     # x13as.exe itself was ended


def test_sa_candidates_from_registry():
    c = sa_candidates()
    assert not c["sa"].any() and (c["role"] == "primary").all()
    assert c["var"].str.match(r"^(Y|LCPI)_").all()
    tickers = set(c["ticker"])
    assert {"CPALEMU Index", "INBGGDRQ Index", "CNCPIMOM Index", "IDGDPY Index"} <= tickers
    assert "CPI INDX Index" not in tickers                   # US CPI is already SA
    assert "5329R002 Index" not in tickers                   # HK GDP history is not used by P1.13
