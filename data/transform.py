"""Series transformations shared by the data pipeline (plan tasks P1.11, P1.13).

    to_quarterly  daily/monthly -> quarterly (mean, sum or last), dropping an incomplete final quarter
    splice        extend a core series with another before or after it, shifted by the
                  mean gap over the overlap (level shift for rates, ratio for indices)
    build_rs      3M interbank rate RS: SIBOR, with SORA after and the IMF rate before (P1.11)

Usage:
    from data.transform import build_rs
    rs, splices = build_rs()          # quarterly % p.a., plus the shifts applied
"""

import numpy as np
import pandas as pd

AGGREGATIONS = {"mean", "sum", "last"}


def to_quarterly(series, how="mean", complete_only=True):
    """Aggregate a daily or monthly PeriodIndex series to quarters.

    complete_only drops the final quarter when the data stop before its last month
    (daily data: more than a week before the quarter's last day), and (for sums of
    monthly data) any quarter with fewer than three months.
    """
    if how not in AGGREGATIONS:
        raise ValueError(f"how must be one of {sorted(AGGREGATIONS)}, got {how!r}")
    s = series.dropna()
    if s.index.freqstr.startswith("Q"):
        return s.copy()
    quarters = s.index.asfreq("Q")
    grouped = s.groupby(quarters)
    out = grouped.agg(how)
    if complete_only and len(s):
        last = s.index[-1]
        quarter_end = last.asfreq("Q").end_time.normalize()
        if last.month % 3 != 0 or (last.freqstr.startswith("D")
                                   and (quarter_end - last.start_time).days > 7):
            out = out.iloc[:-1]
        if how == "sum" and s.index.freqstr.startswith("M"):
            out = out[grouped.size().reindex(out.index) == 3]
    out.index = pd.PeriodIndex(out.index, freq="Q", name=series.index.name)
    return out.rename(series.name)


def splice(core, other, side, how="level", join=None):
    """Extend `core` with `other` on one side ('before' or 'after').

    `other` is shifted by its mean gap to `core` over their overlap: an additive
    shift (how='level', for rates) or a multiplicative one (how='ratio', for
    indices). With `join=n`, only the n overlapping periods nearest the join are
    used, so the two series meet where they are spliced even if they drift apart
    later. Returns (spliced series, metadata dict).
    """
    if side not in {"before", "after"}:
        raise ValueError(f"side must be 'before' or 'after', got {side!r}")
    core, other = core.dropna(), other.dropna()
    overlap = core.index.intersection(other.index)
    if overlap.empty:
        raise ValueError(f"{other.name} and {core.name} do not overlap; can't estimate the splice shift")
    if join:
        overlap = overlap[:join] if side == "before" else overlap[-join:]
    if how == "level":
        shift = float((core[overlap] - other[overlap]).mean())
        adjusted = other + shift
    elif how == "ratio":
        shift = float(np.exp(np.log(core[overlap] / other[overlap]).mean()))
        adjusted = other * shift
    else:
        raise ValueError(f"how must be 'level' or 'ratio', got {how!r}")
    if side == "before":
        extension = adjusted[adjusted.index < core.index[0]]
    else:
        extension = adjusted[adjusted.index > core.index[-1]]
    spliced = pd.concat([extension, core]).sort_index().rename(core.name)
    meta = {"core": core.name, "other": other.name, "side": side, "how": how, "shift": shift,
            "overlap": f"{overlap[0]}-{overlap[-1]}", "overlap_n": len(overlap),
            "extended": f"{extension.index[0]}-{extension.index[-1]}" if len(extension) else None}
    return spliced, meta


def build_rs(vintage=None, registry=None):
    """Quarterly RS (3M interbank rate, % p.a.), decision P1.11: SIBOR core; SORA after and
    the IMF money-market rate before, each level-shifted by its mean gap to SIBOR over the overlap.
    Tickers come from the registry roles (primary / post / history). Returns (series, [splice metadata]).
    """
    from data.collect_data import load_series
    from data.tickers import select

    def quarterly(role):
        row = select(var="RS", role=role, registry=registry)
        if len(row) != 1:
            raise ValueError(f"expected one RS series with role {role!r}, found {len(row)}")
        row = row.iloc[0]
        return to_quarterly(load_series(row["ticker"], row["freq"], vintage=vintage), "mean")

    rs, after = splice(quarterly("primary"), quarterly("post"), "after")
    rs, before = splice(rs, quarterly("history"), "before")
    return rs.rename("RS"), [before, after]
