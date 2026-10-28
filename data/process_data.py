"""Cached Bloomberg data -> model-ready quarterly panel (plan tasks P1.13, P1.13a, P1.15).

Reads one cached vintage (latest by default; never calls Bloomberg) and builds
the panel in data/panel.py's contract, using the README transformations:

    LGDP        100*ln real GDP (SA level)
    LCPI        100*ln CPI (SA), quarterly mean of monthly
    UNR         unemployment rate, %
    RS          3M interbank rate, % p.a. -- SIBOR / SORA / IMF splice (P1.11)
    LS          100*ln S$NEER -- BIS broad NEER, IMF NEER ratio-spliced before 1994 (D2)
    CSI         credit spread indicator (P1.13a, D3): mean of the z-scored loan-deposit
                spread and banks' NIM available each quarter, rescaled to spread pp
    YF          PROVISIONAL foreign output gap: export-share-weighted HP(1600) gaps
    LCPIF       PROVISIONAL foreign CPI: import-share-weighted, chain-linked, 100*ln
    RR_US       US 3M T-bill minus UMich 1-year expected inflation, % p.a.
    RR_US_BAR   Holston-Laubach-Williams US r*, %
    CAPREQ_BAR  Tier 1 minimum + conservation buffer, % (config/capreq.yaml)

YF / LCPIF are provisional until P3.7-P3.9 (decision 2026-10-27): countries are
weighted directly, not via GPM7 blocs. Every column's sources and
transformations are written to outputs/lineage.csv.

Outputs:
    data/processed/panel.parquet          the panel (git-ignored)
    data/processed/panel.json             vintage, build time, seasonal-adjustment methods
    data/foreign/foreign_panel.parquet    per-country LGDP_cc, GAP_cc, LCPI_cc (git-ignored)
    outputs/lineage.csv                   model variable <- transformation <- ticker/field <- vintage

Usage:
    python -m data.process_data [--vintage YYYY-MM-DD]
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.tsa.filters.hp_filter import hpfilter

from data.bloomberg import list_vintages
from data.capreq import CAPREQ_PATH, capreq_series
from data.collect_data import load_series
from data.panel import COLUMNS, PANEL_PATH
from data.seasonal import adjust
from data.tickers import load_registry, select
from data.transform import build_rs, splice, to_quarterly

ROOT = Path(__file__).resolve().parent.parent
FOREIGN_PANEL_PATH = ROOT / "data" / "foreign" / "foreign_panel.parquet"
LINEAGE_PATH = ROOT / "outputs" / "lineage.csv"

WEIGHT_WINDOW = ("2003-01", "2025-12")   # every trade partner reports throughout (Indonesia from 2003)
HP_LAMBDA = 1600
MIN_WEIGHT = 0.5                         # YF / LCPIF need countries covering half the trade weight
MIN_INDEX_VALUE = 0.05                   # 4-decimal index values below this carry > 0.1% rounding error
JOIN_QUARTERS = 4                        # LS back-cast and CSI segments matched over 4 quarters at each join
PARTNER_ALIAS = {"EZ": "EU", "JP": "JA", "CN": "CH"}   # foreign-section country key -> trade partner code


def log100(s):
    return 100 * np.log(s)


def _runs(s):
    """(start, end) positions of each unbroken run of consecutive periods in a PeriodIndex series."""
    breaks = np.flatnonzero(np.diff(s.index.asi8) != 1)
    return list(zip(np.r_[0, breaks + 1], np.r_[breaks, len(s) - 1], strict=True))


def _contiguous_tail(s):
    """The last unbroken run of a PeriodIndex series (chaining growth rates across a gap is invalid)."""
    s = s.dropna()
    if s.empty:
        return s
    return s.iloc[_runs(s)[-1][0]:]


def _regular_until(s, min_run=4):
    """The series up to the end of its last run of >= min_run consecutive periods.

    Cuts off a tail that has turned sparse, e.g. a quarterly series reported only
    half-yearly from some date (bank NIM from 2020).
    """
    s = s.dropna()
    ends = [end for start, end in _runs(s) if end - start + 1 >= min_run]
    return s.iloc[:ends[-1] + 1] if ends else s.iloc[:0]


def chain(growth, form):
    """Level index (base 100 the period before the first rate) from growth rates in %: qoq, qoq_saar,
    or monthly m/m given as 'qoq'. Uses only the last unbroken run of rates."""
    g = _contiguous_tail(growth) / 100
    if form == "qoq_saar":
        g = (1 + g) ** 0.25 - 1
    return 100 * (1 + g).cumprod()


def bridge_break(level, yoy, at, periods=4):
    """Rescale a level series before a break so growth across it matches published y/y rates.

    For each of the first `periods` periods t from the break `at`, the factor is
    level[t] / (level[t-periods] * (1 + yoy[t]/100)); the part before `at` is multiplied by
    their geometric mean. Returns (bridged level, factor).
    """
    at = pd.Period(at, level.index.freq)
    after = level.index[level.index >= at][:periods]
    ratios = [level[t] / (level[t - periods] * (1 + yoy[t] / 100)) for t in after]
    factor = float(np.exp(np.mean(np.log(ratios))))
    bridged = level.copy()
    bridged[bridged.index < at] *= factor
    return bridged, factor


def chain_yoy(growth, periods=4):
    """Level from y/y growth in %: the first `periods` values are set to 100 (an NSA anchor year)."""
    g = _contiguous_tail(growth) / 100
    level = pd.Series(np.nan, index=g.index)
    level.iloc[:periods] = 100.0
    for i in range(periods, len(g)):
        level.iloc[i] = level.iloc[i - periods] * (1 + g.iloc[i])
    return level


class Builder:
    """Loads registry series from one cached vintage and records lineage as it goes."""

    def __init__(self, vintage=None, registry=None):
        vintages = list_vintages()
        if vintage is None:
            if not vintages:
                raise FileNotFoundError("No Bloomberg vintages cached; run data.collect_data first.")
            vintage = vintages[-1]
        self.vintage = vintage
        self.registry = load_registry() if registry is None else registry
        self.lineage = []
        self.sa_methods = {}

    def note(self, var, source, field, transform, provisional=False):
        self.lineage.append({"var": var, "source": source, "field": field, "transform": transform,
                             "vintage": self.vintage, "provisional": provisional})

    def rows(self, **filters):
        return select(registry=self.registry, **filters)

    def one(self, **filters):
        rows = self.rows(**filters)
        if len(rows) != 1:
            raise ValueError(f"expected exactly one registry row for {filters}, found {len(rows)}")
        return rows.iloc[0]

    def load(self, row):
        return load_series(row["ticker"], row["freq"], field=row["field"], vintage=self.vintage)

    def quarterly(self, row, how="mean"):
        return to_quarterly(self.load(row), how)

    def seasonal(self, series, ticker):
        sa, method = adjust(series)
        self.sa_methods[ticker] = method
        return sa


# --------------------------------------------------------------------------- domestic observables

def build_lgdp(b):
    row = b.one(var="LGDP", role="primary")
    b.note("LGDP", row["ticker"], row["field"], "SA real GDP level (quarterly) -> 100*ln")
    return log100(b.quarterly(row))


def build_lcpi(b):
    row = b.one(var="LCPI", role="primary")
    b.note("LCPI", row["ticker"], row["field"], "SA CPI (monthly) -> quarterly mean -> 100*ln")
    return log100(b.quarterly(row))


def build_unr(b):
    row = b.one(var="UNR", role="primary")
    b.note("UNR", row["ticker"], row["field"], "SA unemployment rate, quarterly, %")
    return b.quarterly(row)


def build_rs_column(b):
    rs, splices = build_rs(vintage=b.vintage, registry=b.registry)
    core = b.one(var="RS", role="primary")
    b.note("RS", core["ticker"], core["field"], "daily 3M SIBOR -> quarterly mean (core)")
    for meta in splices:
        other = b.rows(var="RS", group="interest_rate")
        field = other.loc[other["ticker"] == meta["other"], "field"].iloc[0]
        b.note("RS", meta["other"], field,
               f"quarterly mean, level-shifted {meta['shift']:+.3f} pp (mean gap to SIBOR over "
               f"{meta['overlap']}), spliced {meta['side']} for {meta['extended']}")
    return rs


def build_ls(b):
    core = b.one(var="LS", group="neer", role="primary")
    hist = b.one(var="LS", group="neer", role="history")
    ls, meta = splice(b.quarterly(core), b.quarterly(hist), "before", how="ratio", join=JOIN_QUARTERS)
    b.note("LS", core["ticker"], core["field"], "monthly BIS broad NEER -> quarterly mean -> 100*ln (D2)")
    b.note("LS", hist["ticker"], hist["field"],
           f"quarterly mean, ratio-spliced before BIS (x{meta['shift']:.4f}, overlap {meta['overlap']}) "
           f"for {meta['extended']}")
    return log100(ls)


# --------------------------------------------------------------------------- CSI (P1.13a)

def csi_components(b):
    """Quarterly loan-deposit spread (pp) and mean bank NIM (%)."""
    def spliced(group):
        core = b.one(group=group, role="primary")
        hist = b.one(group=group, role="history")
        series, meta = splice(b.quarterly(core), b.quarterly(hist), "before")
        b.note("CSI", core["ticker"], core["field"], f"{group}: monthly -> quarterly mean")
        b.note("CSI", hist["ticker"], hist["field"],
               f"{group}: back-cast {meta['extended']}, level-shifted {meta['shift']:+.3f} pp")
        return series

    lending, deposit = spliced("csi_lending_rates"), spliced("csi_deposit_rates")
    spread = (lending - deposit).dropna().rename("spread")
    group = "csi_net_interest_margin"
    posts = b.rows(group=group, role="post")
    banks = []
    for _, core in b.rows(group=group, role="primary").iterrows():
        post = posts[posts["ticker"] == core["ticker"]].iloc[0]
        regular = _regular_until(b.quarterly(core))
        series, meta = splice(regular, b.quarterly(post), "after")
        banks.append(series.rename(core["ticker"]))
        b.note("CSI", core["ticker"], core["field"],
               f"bank NIM (trailing 12m, %), used to {regular.index[-1]} (sparse afterwards)")
        b.note("CSI", post["ticker"], post["field"],
               f"bank NIM (company basis, %) for {meta['extended']}, level-shifted {meta['shift']:+.3f} pp "
               f"(mean gap over {meta['overlap']})")
    nim = pd.concat(banks, axis=1).sort_index().mean(axis=1).rename("nim")
    b.note("CSI", "bank NIM", None, "mean across the banks with data each quarter")
    return spread, nim


def build_csi(spread, nim, window=None, variant="blend", join=JOIN_QUARTERS):
    """CSI in pp of the spread: mean of available z-scores (D3), or the spread alone (variant='spread').

    z-scores use `window` = (start, end) quarters if given, else each component's full sample.
    The blend has three segments -- spread only, both, NIM only. With `join`, the one-component
    segments are level-shifted to meet the blend over the `join` quarters of the both-component
    period nearest them, so a component starting or stopping causes no step (decision 2026-10-27).
    """
    def z(s):
        ref = s.loc[window[0]:window[1]] if window else s
        return (s - ref.mean()) / ref.std()

    if variant == "spread":
        zc = z(spread)
    elif variant == "blend":
        zs, zn = z(spread).sort_index(), z(nim).sort_index()
        zc = pd.concat([zs, zn], axis=1).sort_index().mean(axis=1)    # mean of whichever exist
        both = zs.index.intersection(zn.index)
        if join and len(both):
            for edge, near in ((zc.index < both[0], both[:join]), (zc.index > both[-1], both[-join:])):
                if edge.any():
                    alone = zs if zs.index.isin(zc.index[edge]).any() else zn
                    zc[edge] += (zc[near] - alone[near]).mean()
    else:
        raise ValueError(f"variant must be 'blend' or 'spread', got {variant!r}")
    ref = spread.loc[window[0]:window[1]] if window else spread
    return (ref.mean() + ref.std() * zc).rename("CSI")


# --------------------------------------------------------------------------- US and policy inputs

def build_rr_us(b):
    nominal = b.one(var="RS_US", role="primary")
    expected = b.one(var="PIE_EXP_US", role="primary")
    b.note("RR_US", nominal["ticker"], nominal["field"], "3M T-bill, daily -> quarterly mean")
    b.note("RR_US", expected["ticker"], expected["field"],
           "UMich 1y expected inflation, monthly -> quarterly mean; RR_US = T-bill - expected inflation")
    return (b.quarterly(nominal) - b.quarterly(expected)).dropna()


def build_rr_us_bar(b):
    row = b.one(var="RR_US_BAR", role="primary")
    b.note("RR_US_BAR", row["ticker"], row["field"], "HLW US r*, quarterly, %")
    return b.quarterly(row)


def build_capreq(b, start, end):
    b.note("CAPREQ_BAR", CAPREQ_PATH.relative_to(ROOT).as_posix(), None,
           "Tier 1 minimum + conservation buffer in force at quarter end (P1.7)")
    return capreq_series(start, end)


# --------------------------------------------------------------------------- foreign inputs (provisional)

def countries(b):
    """Every country with a primary GDP or CPI series: the foreign section plus the US."""
    keys = [k for k, spec in b.registry.get("foreign", {}).items() if "gdp" in spec or "cpi" in spec]
    return ["US", *keys]


def country_gdp(b, cc):
    """100*ln SA real GDP level for a country, built from its primary series' form."""
    row = b.one(var=f"Y_{cc}", role="primary")
    s = b.quarterly(row)
    form = row["form"]
    if form in {"qoq", "qoq_saar"}:
        level = chain(s, form)
    elif form == "yoy":
        level = chain_yoy(s, periods=4)
    else:
        level = s
    steps = [f"{form} -> level" if form not in {"level", "index"} else form]
    if form not in {"level", "index"} and level.index[0] > s.dropna().index[0]:
        steps.append(f"chained from {level.index[0]} (last unbroken run)")
    if form == "yoy":
        steps.append("anchor year set flat at 100, so each quarter is its own y/y chain "
                     "(seasonal pattern not observed; known_gaps.indonesia_gdp_level)")
    if isinstance(row["break"], str):
        hist = b.one(var=f"Y_{cc}", role="history")
        level, factor = bridge_break(level, b.quarterly(hist), row["break"])
        steps.append(f"level break at {row['break']} bridged with {hist['ticker']} y/y "
                     f"(earlier levels x{factor:.4f})")
    if not row["sa"]:
        level = b.seasonal(level, row["ticker"])
        steps.append(f"seasonally adjusted ({b.sa_methods[row['ticker']]})")
    b.note(f"LGDP_{cc}", row["ticker"], row["field"], ", ".join([*steps, "100*ln"]), provisional=True)
    return log100(level)


def country_cpi(b, cc):
    """100*ln SA CPI (quarterly mean) for a country."""
    row = b.one(var=f"LCPI_{cc}", role="primary")
    monthly = b.load(row)
    steps = [row["form"]]
    if row["form"] == "qoq":                       # monthly m/m % (China): chain into an index
        monthly = chain(monthly, "qoq")
        steps = [f"m/m % chained into an index from {monthly.index[0]}"]
    elif (monthly < MIN_INDEX_VALUE).any():
        # 4-decimal indices round to ~0 in hyperinflation (Brazil, Peru): drop imprecise values
        monthly = _contiguous_tail(monthly.where(monthly >= MIN_INDEX_VALUE))
        steps.append(f"values < {MIN_INDEX_VALUE} dropped (rounding), starts {monthly.index[0]}")
    if not row["sa"]:
        monthly = b.seasonal(monthly, row["ticker"])
        steps.append(f"seasonally adjusted ({b.sa_methods[row['ticker']]})")
    b.note(f"LCPI_{cc}", row["ticker"], row["field"], ", ".join([*steps, "quarterly mean", "100*ln"]),
           provisional=True)
    return log100(to_quarterly(monthly, "mean"))


def trade_shares(b, group):
    """Average share of each partner in a trade group's primary series over WEIGHT_WINDOW."""
    rows = b.rows(group=group, role="primary")
    totals = {r["partner"]: b.load(r).loc[WEIGHT_WINDOW[0]:WEIGHT_WINDOW[1]].sum()
              for _, r in rows.iterrows()}
    shares = pd.Series(totals)
    return shares / shares.sum()


def weighted(frame, weights, min_weight=MIN_WEIGHT):
    """Weighted mean across columns, renormalised over non-missing entries each period."""
    w = pd.DataFrame(np.broadcast_to(weights[frame.columns].to_numpy(), frame.shape),
                     index=frame.index, columns=frame.columns).where(frame.notna())
    covered = w.sum(axis=1)
    out = (frame * w).sum(axis=1) / covered
    return out[covered >= min_weight * weights[frame.columns].sum()]


def build_foreign(b):
    """Provisional YF and LCPIF, plus the per-country foreign panel."""
    export_w = trade_shares(b, "total_exports_by_partner")
    import_w = trade_shares(b, "imports_by_partner")
    lgdp, gaps, lcpi = {}, {}, {}
    for cc in countries(b):
        partner = PARTNER_ALIAS.get(cc, cc)
        if partner not in export_w:
            continue
        lgdp[cc] = country_gdp(b, cc)
        cycle, _ = hpfilter(lgdp[cc].dropna(), lamb=HP_LAMBDA)
        gaps[cc] = cycle
        lcpi[cc] = country_cpi(b, cc)
    alias = {cc: PARTNER_ALIAS.get(cc, cc) for cc in lgdp}
    omega = pd.Series({cc: export_w[p] for cc, p in alias.items()})
    xi = pd.Series({cc: import_w[p] for cc, p in alias.items()})

    yf = weighted(pd.DataFrame(gaps), omega).rename("YF")
    dlcpi = pd.DataFrame(lcpi).diff()
    lcpif_growth = weighted(dlcpi, xi)
    if len(_runs(lcpif_growth)) > 1:              # cumsum would silently bridge the gap
        raise ValueError("LCPIF coverage drops below MIN_WEIGHT mid-sample; can't chain-link across it")
    lcpif =(log100(100) + lcpif_growth.cumsum()).rename("LCPIF")
    b.note("YF", "LGDP_cc (foreign panel)", None,
           f"HP(lambda={HP_LAMBDA}) gap per country; weighted by total-export shares "
           f"{WEIGHT_WINDOW[0]}..{WEIGHT_WINDOW[1]}, renormalised over countries with data; quarters "
           f"with < {MIN_WEIGHT:.0%} of the weight covered dropped (starts {yf.index[0]})", provisional=True)
    b.note("LCPIF", "LCPI_cc (foreign panel)", None,
           f"import-share-weighted q/q log change ({WEIGHT_WINDOW[0]}..{WEIGHT_WINDOW[1]} shares, "
           f">= {MIN_WEIGHT:.0%} of the weight covered), chain-linked from 100*ln(100)", provisional=True)

    foreign = pd.concat({**{f"LGDP_{k}": v for k, v in lgdp.items()},
                         **{f"GAP_{k}": v for k, v in gaps.items()},
                         **{f"LCPI_{k}": v for k, v in lcpi.items()}}, axis=1).sort_index()
    return yf, lcpif, foreign, {"omega": omega.round(4).to_dict(), "xi": xi.round(4).to_dict()}


# --------------------------------------------------------------------------- assembly

def build_panel(vintage=None, csi_window=None, registry=None):
    """Return (panel, foreign panel, lineage DataFrame, metadata dict)."""
    b = Builder(vintage, registry)
    spread, nim = csi_components(b)
    columns = {
        "LGDP": build_lgdp(b),
        "UNR": build_unr(b),
        "LCPI": build_lcpi(b),
        "RS": build_rs_column(b),
        "LS": build_ls(b),
        "CSI": build_csi(spread, nim, window=csi_window),
        "RR_US": build_rr_us(b),
        "RR_US_BAR": build_rr_us_bar(b),
    }
    b.note("CSI", "spread + NIM", None,
           f"CSI = mean of available z-scores (spread {spread.index[0]}-{spread.index[-1]}, "
           f"NIM {nim.index[0]}-{nim.index[-1]}) rescaled to spread pp; one-component segments "
           f"level-matched to the blend over {JOIN_QUARTERS} quarters at each join; "
           f"z window = {csi_window or 'full sample per component'}")
    yf, lcpif, foreign, weights = build_foreign(b)
    columns["YF"], columns["LCPIF"] = yf, lcpif

    start = min(s.dropna().index.min() for s in columns.values())
    end = max(s.dropna().index.max() for s in columns.values())
    columns["CAPREQ_BAR"] = build_capreq(b, start, end)
    index = pd.period_range(start, end, freq="Q", name="quarter")
    panel = pd.DataFrame({k: v.reindex(index) for k, v in columns.items()})[COLUMNS]

    meta = {"vintage": b.vintage, "built_at": dt.datetime.now().isoformat(timespec="seconds"),
            "csi_window": csi_window, "seasonal_adjustment": b.sa_methods, "weights": weights,
            "provisional": ["YF", "LCPIF"]}
    return panel, foreign, pd.DataFrame(b.lineage), meta


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the model-ready panel from cached Bloomberg data.")
    parser.add_argument("--vintage", help="Bloomberg vintage YYYY-MM-DD (default: latest cached)")
    args = parser.parse_args(argv)

    panel, foreign, lineage, meta = build_panel(args.vintage)
    for path in (PANEL_PATH, FOREIGN_PANEL_PATH, LINEAGE_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(PANEL_PATH)
    PANEL_PATH.with_suffix(".json").write_text(json.dumps(meta, indent=2, default=str))
    foreign.to_parquet(FOREIGN_PANEL_PATH)
    lineage.to_csv(LINEAGE_PATH, index=False)

    spans = {c: f"{panel[c].first_valid_index()}-{panel[c].last_valid_index()}" for c in panel.columns}
    print(f"Panel {panel.index[0]}-{panel.index[-1]} from vintage {meta['vintage']} -> {PANEL_PATH}")
    for col, span in spans.items():
        flag = "  (provisional)" if col in meta["provisional"] else ""
        print(f"  {col:11s} {span}  n={panel[col].notna().sum()}{flag}")
    print(f"Foreign panel: {foreign.shape[1]} series -> {FOREIGN_PANEL_PATH}")
    print(f"Lineage: {len(lineage)} rows -> {LINEAGE_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
