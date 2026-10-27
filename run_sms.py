"""End-to-end SMS pipeline runner.

Each step is a subcommand; with no step, all steps run in order. Steps not yet
built are stubs that say which plan task implements them.

Every run writes outputs/{run_id}/meta.json (mode, seed, git commit, config
hashes) -- see "Reproducibility" in IMPLEMENTATION_PLAN.md.

Usage:
    python run_sms.py --synthetic            # whole pipeline on synthetic data, no Bloomberg
    python run_sms.py data                   # one step
    python run_sms.py --synthetic --seed 3 estimate
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from data.panel import SYNTHETIC_ENV, load_panel, synthetic_mode

ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
OUTPUT_DIR = ROOT / "outputs"


def step_data(run):
    panel = load_panel(seed=run["seed"])
    panel.to_parquet(run["dir"] / "panel.parquet")
    print(f"[data] panel {panel.index[0]}-{panel.index[-1]}, {panel.shape[1]} series "
          f"({'synthetic' if run['synthetic'] else 'real'})")


def _stub(task):
    def step(run):
        print(f"[stub] not implemented yet ({task})")
    return step


STEPS = {
    "data": step_data,
    "estimate": _stub("P4"),
    "irf": _stub("P2.8"),
    "simulate": _stub("P2.10, P5.9"),
    "backtest": _stub("P5B"),
    "report": _stub("P6.8"),
}


def _git_commit():
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    except OSError:
        return None
    return out.stdout.strip() or None


def _config_hashes():
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        for p in sorted(CONFIG_DIR.glob("*.yaml"))
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the SMS pipeline.")
    parser.add_argument("step", nargs="?", choices=list(STEPS), help="run one step (default: all)")
    parser.add_argument("--synthetic", action="store_true",
                        help=f"use synthetic data, no Bloomberg (same as {SYNTHETIC_ENV}=1)")
    parser.add_argument("--seed", type=int, default=0, help="random seed (default 0)")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)

    if args.synthetic:
        os.environ[SYNTHETIC_ENV] = "1"
    synthetic = synthetic_mode()

    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + ("-synthetic" if synthetic else "")
    run_dir = args.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    steps = [args.step] if args.step else list(STEPS)
    meta = {
        "run_id": run_id,
        "synthetic": synthetic,
        "seed": args.seed,
        "steps": steps,
        "git_commit": _git_commit(),
        "config_hashes": _config_hashes(),
        "python": sys.version.split()[0],
        "started_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"run {run_id} -> {run_dir}")

    run = {"id": run_id, "dir": run_dir, "seed": args.seed, "synthetic": synthetic}
    for name in steps:
        try:
            STEPS[name](run)
        except FileNotFoundError as exc:
            print(f"[{name}] {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
