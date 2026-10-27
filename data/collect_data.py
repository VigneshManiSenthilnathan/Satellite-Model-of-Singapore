"""Pull every registry series from Bloomberg into the local cache, then re-verify the registry (P1.6b).

Every ticker in config/tickers.yaml is pulled at its native frequency (daily,
monthly or quarterly) from 1980, one request per series, through
data.bloomberg -- so each series has its own cache file and editing one
registry entry re-pulls only that series. Quarterly aggregation (averages for
rates and indices, sums for flows) happens later, in P1.13.

Consensus (ECFC) tickers are pulled for the current and next calendar year,
sampled at month-ends. Their history for the backtest is a separate step (P5B).

After the pull, the registry is re-verified:
    - every ticker must resolve (bdp NAME)
    - every pulled span is compared with the registry `span`; a moved start or
      an earlier end is a problem, a later end is only reported

Outputs (git-ignored, under data/raw/bloomberg/):
    manifest_YYYY-MM-DD.csv   one row per series: rows, first/last date, pulled span, status
    verify_YYYY-MM-DD.csv     re-verification findings

Usage:
    python -m data.collect_data                 # pull (cache hits are free) + verify
    python -m data.collect_data --refresh       # force live pulls
    python -m data.collect_data --years 2026 2027
"""

import argparse
import datetime as dt
import sys

import pandas as pd

from data import tickers
from data.bloomberg import (
    CACHE_DIR,
    BloombergError,
    BloombergSecurityError,
    BloombergSessionError,
    bdh,
    bdp,
)
from data.panel import SYNTHETIC_ENV, synthetic_mode

START = "1980-01-01"
PERIODICITY = {"D": "DAILY", "M": "MONTHLY", "Q": "QUARTERLY"}
DEFAULT_FREQ = "M"      # trade rows carry no freq; the registry's trade section is all monthly
CONSENSUS_FREQ = "M"    # consensus values sampled at month-ends

ITEM_COLUMNS = ["section", "group", "country", "ticker", "field", "var", "role", "freq", "span", "status"]


def default_years(today=None):
    today = today or dt.date.today()
    return [today.year, today.year + 1]


def pull_list(years=None, registry=None):
    """Every (ticker, field, freq) to pull: registry series plus expanded consensus tickers."""
    registry = tickers.load_registry() if registry is None else registry
    default_field = registry.get("meta", {}).get("default_field", "PX_LAST")
    items = tickers.series(registry)[ITEM_COLUMNS].copy()
    items["freq"] = items["freq"].fillna(DEFAULT_FREQ)

    consensus = []
    for year in default_years() if years is None else years:
        for row in tickers.consensus_tickers(year, registry=registry).itertuples(index=False):
            consensus.append({"section": "consensus", "group": row.kind, "country": row.country,
                              "ticker": row.ticker})
        for ticker in tickers.singapore_consensus_tickers(year, registry=registry):
            consensus.append({"section": "consensus", "group": "singapore", "country": "SG",
                              "ticker": ticker})
    consensus = pd.DataFrame(consensus, columns=ITEM_COLUMNS, dtype=object)
    consensus = consensus.assign(field=default_field, role="reference", freq=CONSENSUS_FREQ,
                                 status="verified")

    items = pd.concat([items, consensus], ignore_index=True)
    return items.drop_duplicates(["ticker", "field", "freq"]).reset_index(drop=True)


def _span(dates):
    if len(dates) == 0:
        return None
    return f"{pd.Period(dates.min(), 'Q')}-{pd.Period(dates.max(), 'Q')}"


def collect(items, refresh=False, progress=print):
    """Pull every item through the cache. Returns the manifest (one row per item).

    Bad tickers and request errors are recorded and skipped; a session that stays
    down after data.bloomberg's retries stops the run.
    """
    rows = []
    for i, item in enumerate(items.itertuples(index=False), 1):
        record = {**item._asdict(), "periodicity": PERIODICITY[item.freq], "rows": 0,
                  "first": None, "last": None, "span_pulled": None, "result": "ok", "message": ""}
        try:
            df = bdh(item.ticker, item.field, START, periodicity=record["periodicity"],
                     periodicityAdjustment="CALENDAR", refresh=refresh)
        except BloombergSessionError:
            raise
        except BloombergSecurityError as exc:
            record.update(result="bad_ticker", message=str(exc))
        except BloombergError as exc:
            record.update(result="error", message=str(exc))
        else:
            dates = df["date"].dropna()
            record.update(rows=len(df), span_pulled=_span(dates),
                          first=dates.min().date() if len(dates) else None,
                          last=dates.max().date() if len(dates) else None,
                          result="ok" if len(df) else "empty")
        rows.append(record)
        if progress and (i % 25 == 0 or i == len(items)):
            progress(f"  {i}/{len(items)} pulled")
    return pd.DataFrame(rows)


def verify(manifest, names=None):
    """Re-verify the registry against a manifest. Returns findings: ticker, field, check, severity, detail.

    `names` maps ticker -> NAME; by default it is pulled with one bdp request.
    """
    if names is None:
        ref = bdp(sorted(manifest["ticker"].unique()), "NAME")
        names = dict(zip(ref["ticker"], ref["value"], strict=True))
    findings = []

    def add(row, check, severity, detail):
        findings.append({"ticker": row.ticker, "field": row.field, "check": check,
                         "severity": severity, "detail": detail})

    for row in manifest.itertuples(index=False):
        if row.ticker not in names:
            add(row, "resolve", "problem", "ticker does not resolve (no NAME)")
        if row.result != "ok":
            message = row.message if isinstance(row.message, str) else ""   # NaN when read back from CSV
            add(row, "pull", "problem", f"{row.result}: {message}" if message else row.result)
            continue
        if not isinstance(row.span, str) or row.span_pulled is None:
            continue
        reg_start, reg_end = row.span.split("-")
        got_start, got_end = row.span_pulled.split("-")
        if got_start != reg_start:
            add(row, "span_start", "problem", f"registry {reg_start}, pulled {got_start}")
        if pd.Period(got_end, "Q") < pd.Period(reg_end, "Q"):
            add(row, "span_end", "problem", f"ends {got_end}, registry says {reg_end} (series stopped?)")
        elif got_end != reg_end:
            add(row, "span_end", "info", f"extended {reg_end} -> {got_end}")
    return pd.DataFrame(findings, columns=["ticker", "field", "check", "severity", "detail"])


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pull every registry series into the Bloomberg cache.")
    parser.add_argument("--years", type=int, nargs="+",
                        help="consensus target years (default: this and next)")
    parser.add_argument("--refresh", action="store_true", help="force live pulls instead of cache hits")
    args = parser.parse_args(argv)

    if synthetic_mode():
        print(f"collect_data needs Bloomberg; unset {SYNTHETIC_ENV} to run it.", file=sys.stderr)
        return 1

    items = pull_list(args.years)
    print(f"Pulling {len(items)} series ({items['ticker'].nunique()} unique tickers) from {START}")
    manifest = collect(items, refresh=args.refresh)
    today = dt.date.today().isoformat()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    manifest.to_csv(CACHE_DIR / f"manifest_{today}.csv", index=False)

    findings = verify(manifest)
    findings.to_csv(CACHE_DIR / f"verify_{today}.csv", index=False)

    print("\nPull results:", manifest["result"].value_counts().to_dict())
    problems = findings[findings["severity"] == "problem"]
    extended = (findings["severity"] == "info").sum()
    print(f"Verification: {len(problems)} problems, {extended} spans extended since the registry was written")
    if len(problems):
        print(problems.to_string(index=False))
    print(f"\nManifest and findings written to {CACHE_DIR}")
    return 1 if manifest["result"].isin(["bad_ticker", "error"]).any() else 0


if __name__ == "__main__":
    sys.exit(main())
