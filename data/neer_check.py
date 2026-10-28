"""S$NEER validation (plan task P1.12).

Compares the primary S$NEER proxy (BIS broad NEER, decision D2) with the other
proxies in the registry (IMF NEER, Bloomberg SNEER, Goldman Sachs estimate) and
with a simple trade-weighted index (TWI) of S$ bilateral rates:

    TWI growth_t = sum_i w_i * dln(S$ per partner i)_t / sum_i w_i     (over partners quoted at t)

w_i = partner i's share of Singapore's total trade (exports + imports, registry
SEMC*/SIMC* primaries) averaged over WEIGHT_WINDOW. Chain-linking growth rates
lets partners enter mid-sample without level jumps.

Policy episodes (config/mas_policy.yaml): each proxy's annualised trend slope
within each episode is compared with MAS's announced stance -- positive for
"appreciation", |slope| < ZERO_TOL_PA for "zero".

Everything reads cached Bloomberg data (latest vintage by default); no live pulls.

Usage:
    python -m data.neer_check
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from data.collect_data import load_series
from data.tickers import select

WEIGHT_WINDOW = ("2003-01", "2025-12")   # every trade partner (incl. Indonesia) reported throughout
PRIMARY = "NBISSING Index"
POLICY_PATH = Path(__file__).resolve().parent.parent / "config" / "mas_policy.yaml"
MIN_EPISODE_MONTHS = 6     # shorter episodes give no reliable trend
ZERO_TOL_PA = 2.0          # a "zero" episode agrees if |trend slope| < 2% p.a. (the band allows ~+/-2%)


def trade_weights(vintage=None, window=WEIGHT_WINDOW, registry=None):
    """Average total-trade share of each partner with a bilateral S$ rate in the registry."""
    fx = select(group="neer_bilateral", registry=registry)
    flows = select(group=["total_exports_by_partner", "imports_by_partner"], role="primary",
                   registry=registry)
    totals = {}
    for partner in fx["partner"]:
        rows = flows[flows["partner"] == partner]
        if rows.empty:
            continue
        totals[partner] = sum(load_series(t, "M", vintage=vintage).loc[window[0]:window[1]].sum()
                              for t in rows["ticker"])
    weights = pd.Series(totals, name="weight")
    return weights / weights.sum()


def twi(vintage=None, registry=None):
    """Monthly chain-linked trade-weighted S$ index (log level x 100, starts at 0)."""
    fx = select(group="neer_bilateral", registry=registry)
    weights = trade_weights(vintage, registry=registry)
    growth = {}
    for row in fx.itertuples(index=False):
        if row.partner in weights:
            daily = load_series(row.ticker, row.freq, vintage=vintage)
            monthly = daily.groupby(daily.index.asfreq("M")).mean()
            growth[row.partner] = 100 * np.log(monthly).diff()
    growth = pd.DataFrame(growth)
    w = pd.DataFrame(np.broadcast_to(weights[growth.columns].to_numpy(), growth.shape),
                     index=growth.index, columns=growth.columns).where(growth.notna())
    index_growth = (growth * w).sum(axis=1) / w.sum(axis=1)
    index_growth = index_growth[w.sum(axis=1) > 0.5]          # need over half the trade weight quoted
    return index_growth.cumsum().rename("TWI")


def proxies(vintage=None, registry=None):
    """Monthly 100*ln level of every S$NEER proxy, plus the TWI, side by side."""
    out = {}
    for row in select(var="LS", group="neer", registry=registry).itertuples(index=False):
        s = load_series(row.ticker, row.freq, vintage=vintage)
        if row.freq == "D":
            s = s.groupby(s.index.asfreq("M")).mean()
        out[row.ticker] = 100 * np.log(s)
    out["TWI"] = twi(vintage, registry=registry)
    return pd.DataFrame(out)


def compare_proxies(levels, primary=PRIMARY):
    """Each proxy vs the primary: overlap, correlation of monthly and 12-month changes, tracking error."""
    rows = []
    for name in levels.columns.drop(primary):
        both = levels[[primary, name]].dropna()
        m = both.diff().dropna()
        y = both.diff(12).dropna()
        gap = (y[name] - y[primary])
        rows.append({"proxy": name, "overlap": f"{both.index[0]}-{both.index[-1]}", "months": len(both),
                     "corr_monthly": m.corr().iloc[0, 1], "corr_12m": y.corr().iloc[0, 1],
                     "te_12m_pp": gap.std(), "mean_gap_12m_pp": gap.mean()})
    return pd.DataFrame(rows)


def load_decisions(path=POLICY_PATH):
    with open(path, encoding="utf-8") as f:
        return pd.DataFrame(yaml.safe_load(f)["decisions"])


def episodes(decisions, end=None):
    """Policy episodes: a new one starts at any decision that changes the slope or re-centres the band."""
    d = decisions.assign(date=pd.to_datetime(decisions["date"])).sort_values("date")
    starts = d[(d["slope_change"] != "unchanged") | (d["centre"] != "unchanged") | (d.index == d.index[0])]
    end = pd.Timestamp(end or pd.Timestamp.today().normalize())
    rows = []
    for i, (_, row) in enumerate(starts.iterrows()):
        stop = starts["date"].iloc[i + 1] if i + 1 < len(starts) else end
        rows.append({"start": row["date"], "end": stop, "stance": row["slope_stance"],
                     "confidence": row["confidence"]})
    return pd.DataFrame(rows)


def episode_slopes(levels, eps, min_months=MIN_EPISODE_MONTHS):
    """Annualised OLS trend slope (% p.a.) of each proxy per episode, and agreement with the stance."""
    rows = []
    for ep in eps.itertuples(index=False):
        window = levels.loc[pd.Period(ep.start, "M") + 1:pd.Period(ep.end, "M") - 1]   # skip boundary months
        row = {"start": ep.start.date(), "end": ep.end.date(), "stance": ep.stance,
               "confidence": ep.confidence}
        for name in levels.columns:
            s = window[name].dropna()
            if len(s) < min_months:
                row[name] = np.nan
                continue
            slope = np.polyfit(np.arange(len(s)), s.to_numpy(), 1)[0] * 12
            row[name] = slope
        rows.append(row)
    out = pd.DataFrame(rows)
    for name in levels.columns:
        ok = np.where(out["stance"] == "appreciation", out[name] > 0, out[name].abs() < ZERO_TOL_PA)
        out[f"{name}_agrees"] = np.where(out[name].isna(), np.nan, ok)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate the S$NEER proxy (P1.12).")
    parser.add_argument("--vintage", help="Bloomberg vintage (default: latest cached)")
    args = parser.parse_args(argv)
    weights = trade_weights(args.vintage)
    print("TWI weights (total-trade shares):", weights.round(3).sort_values(ascending=False).to_dict())
    levels = proxies(args.vintage)
    slopes = episode_slopes(levels, episodes(load_decisions()))
    with pd.option_context("display.width", 250, "display.float_format", "{:.2f}".format):
        print(compare_proxies(levels).to_string(index=False))
        print("\nTrend slope by policy episode (% p.a.):")
        print(slopes[["start", "end", "stance", "confidence", *levels.columns]].to_string(index=False))
    print("\nAgreement with the announced stance (episodes with data):")
    for name in levels.columns:
        a = slopes[f"{name}_agrees"].dropna()
        print(f"  {name:15s} {int(a.sum())}/{len(a)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
