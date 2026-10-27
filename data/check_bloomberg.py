"""Bloomberg Desktop API connectivity check (implementation plan task P0.6).

Runs each link in the chain separately and stops at the first failure with a
hint on how to fix it:

    1. blpapi package imports
    2. Session starts against the Terminal's local API (localhost:8194)
    3. //blp/refdata service opens
    4. Reference data request (NAME) returns a value       -- live pull, cached
    5. Historical data request (PX_LAST, last 10 days)     -- live pull, cached

Steps 4-5 go through data.bloomberg, so both pulls land in the local cache
(data/raw/bloomberg/, git-ignored).

Usage:
    .venv\\Scripts\\python.exe -m data.check_bloomberg [--ticker "USGG3M Index"]
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.bloomberg import (  # noqa: E402
    CACHE_DIR,
    HOST,
    PORT,
    BloombergError,
    BloombergSecurityError,
    BloombergSession,
    bdh,
    bdp,
)


def fail(step, message, hint):
    print(f"[FAIL] {step}: {message}")
    print(f"       Fix: {hint}")
    sys.exit(1)


def ok(step, detail=""):
    print(f"[ OK ] {step}{': ' + detail if detail else ''}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticker", default="USGG3M Index")
    args = parser.parse_args()

    # 1. Import
    try:
        import blpapi
    except ImportError as exc:
        fail(
            "Import blpapi",
            str(exc),
            "activate the project venv (.venv) and run: pip install "
            "--index-url=https://blpapi.bloomberg.com/repository/releases/python/simple/ blpapi",
        )
    ok("Import blpapi", blpapi.__version__)

    # 2-3. Session and service
    bbg = BloombergSession()
    try:
        bbg.__enter__()
    except BloombergError as exc:
        if "refdata" in str(exc):
            fail("Open //blp/refdata", str(exc),
                 "the Terminal may be logged in on another machine, or API access is "
                 "disabled for this login; check WAPI <GO> or ask your Bloomberg admin.")
        fail("Start session", str(exc),
             "open the Bloomberg Terminal and log in (the API only listens while a "
             "user is logged in). If it is open, check that bbcomm.exe is running; "
             "restart it from C:\\blp\\DAPI\\bbcomm.exe or restart the Terminal.")
    ok("Start session", f"{HOST}:{PORT}")
    ok("Open //blp/refdata")

    try:
        # 4. Reference data
        try:
            ref = bdp(args.ticker, "NAME", refresh=True, session=bbg)
        except BloombergSecurityError as exc:
            fail("ReferenceDataRequest", str(exc),
                 f"ticker '{args.ticker}' not recognised; confirm it with SECF <GO>.")
        except BloombergError as exc:
            fail("ReferenceDataRequest", str(exc), "check entitlements; retry or restart the Terminal.")
        if ref.empty:
            fail("ReferenceDataRequest", "no NAME returned", "check entitlements for this ticker.")
        ok("ReferenceDataRequest", f"{args.ticker} -> {ref['value'].iloc[0]}")

        # 5. Historical data
        end = dt.date.today()
        try:
            hist = bdh(args.ticker, "PX_LAST", end - dt.timedelta(days=10), end,
                       refresh=True, session=bbg)
        except BloombergError as exc:
            fail("HistoricalDataRequest", str(exc),
                 "check entitlements for historical data on this ticker.")
        if hist.empty:
            fail("HistoricalDataRequest", "no rows returned",
                 "the ticker may have no recent prints; try --ticker \"SPX Index\".")
        last = hist.iloc[-1]
        ok("HistoricalDataRequest", f"{len(hist)} rows, latest {last['date'].date()} = {last['value']}")
    finally:
        bbg.__exit__(None, None, None)

    print(f"\nBloomberg API is wired up correctly. Pulls cached under {CACHE_DIR}")


if __name__ == "__main__":
    main()
