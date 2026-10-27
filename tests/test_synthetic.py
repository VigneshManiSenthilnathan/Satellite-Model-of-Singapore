"""Synthetic-data mode (P0.7): generator, panel switch, Bloomberg guard, end-to-end run."""

import json

import pandas as pd
import pytest

import run_sms
from data import panel as panel_mod
from data.bloomberg import BloombergError, BloombergSession
from data.panel import COLUMNS, load_panel
from data.synthetic import make_panel


def test_panel_shape_and_index():
    df = make_panel(start="2000Q1", end="2009Q4")
    assert list(df.columns) == COLUMNS
    assert isinstance(df.index, pd.PeriodIndex) and df.index.freqstr.startswith("Q")
    assert len(df) == 40
    assert not df.isna().any().any()


def test_same_seed_same_panel_different_seed_differs():
    pd.testing.assert_frame_equal(make_panel(seed=1), make_panel(seed=1))
    assert not make_panel(seed=1).equals(make_panel(seed=2))


def test_series_are_plausible():
    df = make_panel(seed=0)
    assert (df["UNR"] > 0).all() and (df["RS"] >= 0).all()
    pie = 4 * df["LCPI"].diff().dropna()
    assert 0 < pie.mean() < 4                       # around the 2% anchor
    growth = 4 * df["LGDP"].diff().dropna()
    assert 0 < growth.mean() < 5                    # around 2.5% potential growth


def test_load_panel_switches_on_mode(monkeypatch, tmp_path):
    pd.testing.assert_frame_equal(load_panel(seed=5), make_panel(seed=5))
    monkeypatch.setenv("SMS_SYNTHETIC", "0")
    monkeypatch.setattr(panel_mod, "PANEL_PATH", tmp_path / "missing.parquet")
    with pytest.raises(FileNotFoundError, match="synthetic"):
        load_panel()


def test_bloomberg_refused_in_synthetic_mode():
    with pytest.raises(BloombergError, match="synthetic mode"):
        BloombergSession().__enter__()


def test_run_sms_end_to_end(tmp_path):
    assert run_sms.main(["--synthetic", "--output-dir", str(tmp_path)]) == 0
    (run_dir,) = tmp_path.iterdir()
    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["synthetic"] and meta["steps"] == list(run_sms.STEPS)
    assert "tickers.yaml" in meta["config_hashes"]
    saved = pd.read_parquet(run_dir / "panel.parquet")
    pd.testing.assert_frame_equal(saved, make_panel(seed=0), check_freq=False)
