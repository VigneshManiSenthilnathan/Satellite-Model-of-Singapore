"""Developer task runner (plan task P0.5). Plain Python, so it works without make.

    python tasks.py test [pytest args]      run the test suite (synthetic mode)
    python tasks.py lint                    ruff check
    python tasks.py bloomberg               Bloomberg connectivity check
    python tasks.py collect [args]          pull every registry series into the cache + re-verify
    python tasks.py data|estimate|irf|simulate|backtest|report [run_sms args]
    python tasks.py all [run_sms args]      whole pipeline, e.g. python tasks.py all --synthetic

Pipeline steps forward to run_sms.py, so `python tasks.py irf --synthetic`
is the same as `python run_sms.py --synthetic irf`.
"""

import subprocess
import sys

from run_sms import STEPS

PY = sys.executable


def run(cmd):
    return subprocess.run(cmd).returncode


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    task, rest = argv[0], argv[1:]
    if task == "test":
        return run([PY, "-m", "pytest", *rest])
    if task == "lint":
        return run([PY, "-m", "ruff", "check", ".", *rest])
    if task == "bloomberg":
        return run([PY, "-m", "data.check_bloomberg", *rest])
    if task == "collect":
        return run([PY, "-m", "data.collect_data", *rest])
    if task == "all":
        return run([PY, "run_sms.py", *rest])
    if task in STEPS:
        return run([PY, "run_sms.py", *rest, task])
    print(f"Unknown task {task!r}.\n{__doc__}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
