"""SingStat Table Builder API client with a local parquet cache (plan task P1.8).

Public SingStat tables are the non-Bloomberg cross-check for GDP, CPI and trade
by partner (config/singstat.yaml maps them to registry tickers). The API
returns at most 5,000 data points per call, ordered series by series;
``offset`` counts data points, so a table is fetched page by page until a page
comes back short.

Cache layout mirrors data.bloomberg (git-ignored):

    data/raw/singstat/vintage=YYYY-MM-DD/{table_id}.parquet   long data
    data/raw/singstat/vintage=YYYY-MM-DD/{table_id}.json      title, last update, pull time

A table is fetched at most once a day. ``vintage="YYYY-MM-DD"`` reads the
newest cached copy at or before that date and never calls the API.

Usage:
    from data.singstat import fetch_table
    gdp = fetch_table("M015662")      # columns: series_no, series, period, value, uom

    python -m data.singstat           # fetch the mapped tables, cross-check vs cached Bloomberg
"""

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "singstat.yaml"
LEVEL_TOL_PCT = 1.0       # level checks: mean |Bloomberg/SingStat - 1| above this (%) is flagged
GROWTH_TOL_PP = 0.1       # growth checks: mean |difference in period log change| above this (pp) is flagged
BASE_URL = "https://tablebuilder.singstat.gov.sg/api/table"
PAGE_POINTS = 5000
TIMEOUT_S = 120
CACHE_DIR = Path(__file__).resolve().parent / "raw" / "singstat"
HEADERS = {"User-Agent": "sms-replication", "Accept": "application/json"}

_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


class SingStatError(RuntimeError):
    """The API returned an error or an unexpected payload."""


def parse_period(key):
    """'1975 1Q' -> 1975Q1, '1961 Jan' -> 1961-01, '1975' -> 1975 (annual), '2003 1H' -> 2003 (H1 start)."""
    key = key.strip()
    if m := re.fullmatch(r"(\d{4}) ([1-4])Q", key):
        return pd.Period(f"{m[1]}Q{m[2]}", "Q")
    if m := re.fullmatch(r"(\d{4}) ([A-Z][a-z]{2})", key):
        return pd.Period(year=int(m[1]), month=_MONTHS[m[2]], freq="M")
    if re.fullmatch(r"\d{4}", key):
        return pd.Period(key, "Y")
    if m := re.fullmatch(r"(\d{4}) ([12])H", key):
        return pd.Period(year=int(m[1]), month=6 * int(m[2]) - 5, freq="6M")
    raise SingStatError(f"unrecognised period key {key!r}")


def _get(table_id, offset, http):
    response = http.get(f"{BASE_URL}/tabledata/{table_id}", params={"offset": offset},
                        headers=HEADERS, timeout=TIMEOUT_S)
    response.raise_for_status()
    data = response.json().get("Data")
    if not data:
        raise SingStatError(f"{table_id}: no Data in response")
    return data


def _download(table_id, http):
    rows, meta, offset = [], None, 0
    while True:
        data = _get(table_id, offset, http)
        meta = meta or {"title": data.get("title"), "dataLastUpdated": data.get("dataLastUpdated"),
                        "frequency": data.get("frequency"), "datasource": data.get("datasource")}
        page = data.get("row") or []
        points = 0
        for row in page:
            for col in row["columns"]:
                rows.append((row["seriesNo"], row["rowText"], col["key"], col["value"], row.get("uoM")))
                points += 1
        if points < PAGE_POINTS:
            break
        offset += points
    df = pd.DataFrame(rows, columns=["series_no", "series", "key", "value", "uom"])
    df["period"] = df["key"].map(lambda k: str(parse_period(k)))
    df["value"] = pd.to_numeric(df["value"], errors="coerce")       # "na", "-" -> NaN
    df = df.drop(columns="key").drop_duplicates(["series_no", "period"])
    return df[["series_no", "series", "period", "value", "uom"]], meta


def _lookup(table_id, as_of):
    hits = sorted(p for p in CACHE_DIR.glob(f"vintage=*/{table_id}.parquet")
                  if p.parent.name <= f"vintage={as_of}")
    return hits[-1] if hits else None


def fetch_table(table_id, refresh=False, vintage=None, http=requests):
    """Return a SingStat table as a long DataFrame: series_no, series, period, value, uom."""
    if vintage is not None:
        if refresh:
            raise ValueError("vintage reads are cache-only; refresh=True can't be combined with vintage")
        path = _lookup(table_id, pd.Timestamp(vintage).date().isoformat())
        if path is None:
            raise FileNotFoundError(f"No cached SingStat table {table_id} at or before vintage {vintage}")
        return pd.read_parquet(path)

    today = dt.date.today().isoformat()
    path = CACHE_DIR / f"vintage={today}" / f"{table_id}.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    df, meta = _download(table_id, http)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    meta.update(table_id=table_id, pulled_at=dt.datetime.now().isoformat(timespec="seconds"),
                rows=len(df), series=int(df["series_no"].nunique()))
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    return df


def series(table_id, name, freq, vintage=None, refresh=False):
    """One series from a table as a float Series on a PeriodIndex of the given freq ('M' or 'Q')."""
    df = fetch_table(table_id, refresh=refresh, vintage=vintage)
    rows = df[df["series"] == name]
    if rows.empty:
        raise KeyError(f"{table_id}: no series named {name!r}")
    if rows["series_no"].nunique() > 1:
        numbers = sorted(rows["series_no"].unique())
        raise KeyError(f"{table_id}: series name {name!r} is ambiguous ({numbers})")
    index = pd.PeriodIndex(rows["period"], freq=freq, name="period")
    return pd.Series(rows["value"].to_numpy(), index=index, name=name).sort_index()


# --------------------------------------------------------------------------- cross-check (P1.8 / P1.14)

def load_config(path=CONFIG_PATH):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["tables"]


def compare(bloomberg, singstat, how):
    """Per-period difference on the overlap: % level gap, or pp gap in period log change."""
    both = pd.concat([bloomberg.rename("bbg"), singstat.rename("ss")], axis=1, sort=True).dropna()
    if how == "level":
        return 100 * (both["bbg"] / both["ss"] - 1)
    if how == "growth":
        changes = 100 * np.log(both).diff()
        return (changes["bbg"] - changes["ss"]).dropna()
    raise ValueError(f"compare must be 'level' or 'growth', got {how!r}")


def crosscheck(vintage=None, singstat_vintage=None, config=None):
    """Bloomberg (cached vintage) vs SingStat for every mapped series. One row per series."""
    from data.collect_data import load_series

    rows = []
    for table, spec in (config or load_config()).items():
        units = fetch_table(spec["id"], vintage=singstat_vintage).drop_duplicates("series")
        units = dict(zip(units["series"], units["uom"], strict=True))
        for name, ticker in spec["series"].items():
            ss = series(spec["id"], name, spec["freq"], vintage=singstat_vintage) * spec.get("scale", 1.0)
            bbg = load_series(ticker, spec["freq"], vintage=vintage)
            diff = compare(bbg, ss, spec["compare"])
            tol = LEVEL_TOL_PCT if spec["compare"] == "level" else GROWTH_TOL_PP
            mean_abs = diff.abs().mean() if len(diff) else np.nan
            rows.append({
                "table": table, "singstat": name, "ticker": ticker, "compare": spec["compare"],
                "singstat_uom": units.get(name), "scale": spec.get("scale", 1.0),
                "n": len(diff),
                "first": str(diff.index.min()) if len(diff) else None,
                "last": str(diff.index.max()) if len(diff) else None,
                "mean_abs": mean_abs,
                "max_abs": diff.abs().max() if len(diff) else np.nan,
                "recent_mean_abs": diff.iloc[-12:].abs().mean() if len(diff) else np.nan,
                "flag": "no_overlap" if not len(diff) else ("check" if mean_abs > tol else "ok"),
            })
    return pd.DataFrame(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fetch SingStat tables and cross-check against Bloomberg.")
    parser.add_argument("--vintage", help="Bloomberg vintage to compare (default: latest cached)")
    parser.add_argument("--refresh", action="store_true", help="re-download SingStat tables today")
    args = parser.parse_args(argv)

    config = load_config()
    for spec in config.values():
        fetch_table(spec["id"], refresh=args.refresh)
    result = crosscheck(vintage=args.vintage, config=config)
    out = CACHE_DIR / f"crosscheck_{dt.date.today().isoformat()}.csv"
    result.to_csv(out, index=False)

    with pd.option_context("display.width", 200, "display.float_format", "{:.3f}".format):
        print(result.drop(columns=["first"]).to_string(index=False))
    print(f"\n{(result['flag'] == 'ok').sum()} of {len(result)} series within tolerance "
          f"(level {LEVEL_TOL_PCT}%, growth {GROWTH_TOL_PP} pp). Written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
