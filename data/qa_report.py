"""Data QA report for the model-ready panel (plan task P1.14) -> outputs/data_qa.html.

Reads only cached / processed files (never calls Bloomberg or SingStat):

    data/processed/panel.parquet + panel.json      the panel and its build metadata
    data/foreign/foreign_panel.parquet             per-country foreign series
    outputs/lineage.csv                            sources and transformations
    data/raw/bloomberg/manifest_<vintage>.csv      every collected series (spans, rows)
    data/raw/singstat/crosscheck_*.csv             latest Bloomberg vs SingStat comparison

Sections: panel summary (spans, gaps, outliers), charts of every panel column,
build checks (RS / LS splices, CSI components, bank NIM), foreign inputs and
weights, seasonal-adjustment methods, raw-series coverage, the SingStat
cross-check, and the anomaly list. An anomaly is a period whose change has
|z| > Z_OUTLIER; each is matched against KNOWN_EVENTS and anything unmatched is
listed as unexplained (Phase 1 exit criterion: no unexplained anomalies).

Bloomberg licensing: the report is for internal use; raw series appear only as
charts, and tables hold spans and statistics, not data values. outputs/ is
git-ignored.

Usage:
    python -m data.qa_report [--vintage YYYY-MM-DD]
"""

import argparse
import datetime as dt
import html
import json
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from data.bloomberg import CACHE_DIR
from data.collect_data import load_series
from data.panel import COLUMNS, PANEL_PATH
from data.process_data import FOREIGN_PANEL_PATH, LINEAGE_PATH, Builder, build_csi, csi_components
from data.singstat import CACHE_DIR as SINGSTAT_DIR
from data.transform import build_rs

ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "outputs" / "data_qa.html"
Z_OUTLIER = 4.0
LOG_COLUMNS = {"LGDP", "LCPI", "LS", "LCPIF"}  # shown as annualised q/q % changes
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]
OUTLIER_COLOR = "#d03b3b"

COVID = ("2020Q1", "2021Q4", "COVID-19 lockdowns and rebound")
# (series prefix or exact name, first quarter, last quarter, explanation). First match wins.
KNOWN_EVENTS = [
    ("LGDP", *COVID),
    ("YF", *COVID),
    ("GAP_", *COVID),
    ("LGDP_TW", "2008Q3", "2009Q1", "Global financial crisis: export collapse"),
    ("LGDP_KR", "1998Q1", "1998Q4", "Asian financial crisis"),
    ("GAP_KR", "1998Q1", "1998Q4", "Asian financial crisis"),
    ("LGDP_", *COVID),
    ("UNR", "1998Q3", "1998Q3", "Asian financial crisis"),
    (
        "UNR",
        "2000Q3",
        "2000Q3",
        "In the source: both MOM series (SIQUTOTA, SIUNTOTA) drop 1.4 pp "
        "(Census of Population 2000 benchmark)",
    ),
    ("LCPI", "1981Q1", "1981Q2", "Second oil shock, 1980-81 inflation"),
    ("RS", "1980Q1", "1982Q4", "Volcker-era interest-rate swings (IMF back-cast period)"),
    ("RR_US", "1980Q1", "1982Q4", "Volcker disinflation"),
    ("RR_US_BAR", "2008Q4", "2008Q4", "HLW r* falls in the global financial crisis"),
    ("LS", "1985Q3", "1986Q4", "1985-86 recession: S$ depreciation (IMF NEER back-cast period)"),
    ("CSI", "1982Q1", "1982Q4", "IMF lending/deposit back-cast period (identical to the MAS series)"),
    (
        "CSI",
        "2022Q1",
        "2023Q4",
        "NIM-only period: 2022-23 rate hikes raise NIM, amplified by rescaling to spread pp",
    ),
    ("CAPREQ_BAR", "1998Q4", "2000Q3", "Regulatory steps: Tier 1 12% -> 10% (Dec 1998) -> 8% (Sep 2000)"),
    ("LCPIF", "1980Q1", "1981Q4", "Second oil shock"),
    ("LCPI_US", "1980Q1", "1980Q4", "Second oil shock"),
    ("LCPI_US", "2008Q4", "2008Q4", "Oil-price collapse"),
    ("LCPI_JP", "1980Q1", "1980Q4", "Second oil shock"),
    ("LCPI_KR", "1980Q1", "1980Q4", "Second oil shock"),
    ("LCPI_TW", "1980Q1", "1980Q4", "Second oil shock"),
    ("LCPI_TH", "1980Q1", "1980Q4", "Second oil shock"),
    ("LCPI_GB", "1980Q1", "1980Q4", "Second oil shock"),
    ("LCPI_EZ", "2022Q1", "2022Q4", "Energy-price shock"),
    ("LCPI_IN", "1998Q1", "1998Q4", "1998 food-price spike"),
    ("LCPI_ID", "1997Q4", "1998Q4", "Asian financial crisis: rupiah collapse"),
    ("LCPI_MY", "2008Q3", "2008Q3", "Fuel-subsidy cut (June 2008)"),
    ("LCPI_MY", "2020Q2", "2020Q2", "COVID-19: fuel-price collapse"),
    ("LCPI_PH", "1984Q1", "1984Q4", "Philippine debt crisis"),
    ("LCPI_BR", "1993Q1", "1994Q4", "Hyperinflation before the Real Plan"),
    ("LCPI_MX", "1987Q4", "1988Q1", "1987-88 inflation before the Pacto"),
    ("LCPI_CL", "1984Q4", "1984Q4", "Peso devaluation"),
    ("LCPI_PE", "1990Q1", "1990Q4", "Hyperinflation and the 'Fujishock'"),
]


# --------------------------------------------------------------------------- analysis


def changes(s):
    """Quarterly change for outlier detection: annualised % for 100*ln levels, else the first difference."""
    s = s.dropna()
    return (4 if s.name in LOG_COLUMNS else 1) * s.diff().dropna()


def outliers(s, z=Z_OUTLIER):
    """Periods whose change (or, for gaps, whose level) has |z| > z."""
    x = s.dropna() if str(s.name).startswith(("GAP_", "YF")) else changes(s)
    if len(x) < 8:
        return pd.Series(dtype=float)
    zs = (x - x.mean()) / x.std()
    return zs[zs.abs() > z]


def explain(name, quarter):
    for prefix, first, last, text in KNOWN_EVENTS:
        if (name == prefix or (prefix.endswith("_") and name.startswith(prefix))) and pd.Period(
            first, "Q"
        ) <= quarter <= pd.Period(last, "Q"):
            return text
    return None


STRESS_WINDOWS = {  # name -> (window start, window end); compared with the four quarters before
    "1998 Asian crisis": ("1997Q3", "1998Q4"),
    "2001 tech bust": ("2001Q1", "2001Q4"),
    "2008-09 GFC": ("2008Q3", "2009Q4"),
}


def csi_stress(variants):
    """Change of each CSI variant in each stress window vs the four quarters before it (pp)."""
    rows = []
    for name, (first, last) in STRESS_WINDOWS.items():
        before = pd.period_range(end=pd.Period(first, "Q") - 1, periods=4, freq="Q")
        row = {"episode": name, "window": f"{first}-{last}"}
        for label, s in variants.items():
            s = s.sort_index()
            row[label] = round(float(s.loc[first:last].mean() - s.reindex(before).mean()), 2)
        rows.append(row)
    return pd.DataFrame(rows)


def interior_gaps(s):
    s = s.loc[s.first_valid_index() : s.last_valid_index()] if s.notna().any() else s
    return int(s.isna().sum())


def anomalies(frame):
    rows = []
    for name in frame.columns:
        for quarter, z in outliers(frame[name].rename(name)).items():
            rows.append(
                {
                    "series": name,
                    "quarter": str(quarter),
                    "z": round(float(z), 1),
                    "explanation": explain(name, quarter),
                }
            )
    return pd.DataFrame(rows, columns=["series", "quarter", "z", "explanation"])


def raw_coverage(manifest, vintage):
    """Per collected registry series: span, rows and interior gaps at native frequency."""
    rows = []
    for r in manifest[manifest["section"] != "consensus"].itertuples(index=False):
        gaps = None
        if r.result == "ok" and r.freq in {"M", "Q"}:
            s = load_series(r.ticker, r.freq, field=r.field, vintage=vintage)
            full = pd.period_range(s.index[0], s.index[-1], freq=r.freq)
            gaps = len(full.difference(s.index))
        rows.append(
            {
                "ticker": r.ticker,
                "field": r.field,
                "group": r.group,
                "role": r.role,
                "freq": r.freq,
                "registry span": r.span,
                "pulled span": r.span_pulled,
                "rows": r.rows,
                "interior gaps": gaps,
                "status": r.status,
                "result": r.result,
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- charts


class Charts:
    """Plotly figures as HTML fragments; the plotly.js bundle is inlined once so the file works offline."""

    def __init__(self):
        self.first = True

    def line(self, series, title, yaxis, marks=None):
        fig = go.Figure()
        for i, (name, s) in enumerate(series.items()):
            s = s.dropna()
            fig.add_trace(
                go.Scatter(
                    x=s.index.to_timestamp(),
                    y=s.to_numpy(),
                    name=name,
                    mode="lines",
                    line={"width": 2, "color": SERIES_COLORS[i % len(SERIES_COLORS)]},
                )
            )
        if marks is not None and len(marks):
            fig.add_trace(
                go.Scatter(
                    x=marks.index.to_timestamp(),
                    y=marks.to_numpy(),
                    mode="markers",
                    name=f"|z| > {Z_OUTLIER:g}",
                    marker={"size": 9, "color": OUTLIER_COLOR, "symbol": "diamond"},
                )
            )
        fig.update_layout(
            title={"text": title, "font": {"size": 14}},
            height=300,
            margin={"l": 50, "r": 20, "t": 40, "b": 30},
            hovermode="x unified",
            template="plotly_white",
            showlegend=len(fig.data) > 1,
            legend={"orientation": "h", "y": -0.15},
            yaxis_title=yaxis,
        )
        fig.update_xaxes(showgrid=False)
        fig.update_yaxes(gridcolor="#ececea", zerolinecolor="#c9c8c3")
        out = fig.to_html(
            full_html=False,
            include_plotlyjs="inline" if self.first else False,
            config={"displaylogo": False, "responsive": True},
        )
        self.first = False
        return f'<div class="chart">{out}</div>'


def panel_chart(charts, panel, name):
    s = panel[name].rename(name)
    if name in LOG_COLUMNS:
        shown, unit = changes(s), "% p.a. (4 x q/q log change)"
        title = f"{name}: annualised quarterly change"
    else:
        shown, unit, title = s.dropna(), "level", name
    marks = shown.reindex(outliers(s).index)
    return charts.line({name: shown}, title, unit, marks)


# --------------------------------------------------------------------------- HTML


def table(df, cls=""):
    return df.to_html(index=False, na_rep="", border=0, classes=f"tbl {cls}", escape=True)


CSS = """
:root { --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --rule: #e4e3df;
        --bad: #d03b3b; --good: #0ca30c; }
body { background: var(--surface); color: var(--ink);
       font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
       margin: 0 auto; max-width: 1200px; padding: 16px; }
h1 { font-size: 22px; margin: 8px 0 4px; }
h2 { font-size: 18px; margin-top: 32px; border-bottom: 1px solid var(--rule); }
.meta, .note { color: var(--ink-2); } nav a { margin-right: 12px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(480px, 1fr)); gap: 8px 16px; }
.chart { min-width: 0; }
.tbl { border-collapse: collapse; font-size: 12.5px; margin: 8px 0; width: 100%; }
.tbl th, .tbl td { padding: 3px 8px; border-bottom: 1px solid var(--rule);
                   text-align: left; vertical-align: top; }
.tbl th { color: var(--ink-2); font-weight: 600; }
.wrap { overflow-x: auto; }
.flag { color: var(--bad); font-weight: 600; } .ok { color: var(--good); font-weight: 600; }
"""


def build_report(vintage=None):
    panel = pd.read_parquet(PANEL_PATH)
    meta = json.loads(PANEL_PATH.with_suffix(".json").read_text())
    vintage = vintage or meta["vintage"]
    foreign = pd.read_parquet(FOREIGN_PANEL_PATH)
    lineage = pd.read_csv(LINEAGE_PATH)
    manifest = pd.read_csv(CACHE_DIR / f"manifest_{vintage}.csv")
    crosschecks = sorted(SINGSTAT_DIR.glob("crosscheck_*.csv"))
    charts = Charts()

    # panel summary
    found = anomalies(pd.concat([panel, foreign], axis=1))
    summary = []
    for c in COLUMNS:
        s = panel[c]
        sources = lineage.loc[lineage["var"] == c, "source"].astype(str).tolist()
        summary.append(
            {
                "column": c,
                "first": str(s.first_valid_index()),
                "last": str(s.last_valid_index()),
                "n": int(s.notna().sum()),
                "interior gaps": interior_gaps(s),
                "outliers": int((found["series"] == c).sum()),
                "provisional": "yes" if c in meta["provisional"] else "",
                "sources": ", ".join(dict.fromkeys(sources)),
            }
        )
    summary = pd.DataFrame(summary)
    unexplained = found[found["explanation"].isna()]
    open_items = found[found["explanation"].fillna("").str.contains("open")]

    # build checks
    b = Builder(vintage)
    rs, splices = build_rs(vintage=vintage)
    rs_parts = {"RS (spliced)": rs}
    for m in splices:
        other = load_series(m["other"], "M" if m["side"] == "before" else "D", vintage=vintage)
        q = other.groupby(other.index.asfreq("Q")).mean()
        q.index = pd.PeriodIndex(q.index, freq="Q")
        rs_parts[f"{m['other']} {m['shift']:+.2f} pp"] = q + m["shift"]
    spread, nim = csi_components(b)
    csi = {
        "CSI blend (D3)": build_csi(spread, nim).sort_index(),
        "spread only": build_csi(spread, nim, variant="spread").sort_index(),
        "NIM, rescaled to spread pp": ((nim - nim.mean()) / nim.std() * spread.std() + spread.mean()),
    }
    ls_rows = lineage[lineage["var"] == "LS"]
    banks = {}
    for r in b.rows(group="csi_net_interest_margin").itertuples(index=False):
        banks[f"{r.ticker.split()[0]} {r.field}"] = load_series(r.ticker, "Q", field=r.field, vintage=vintage)

    parts = [
        f"<h1>SMS data QA report</h1><p class='meta'>Vintage {vintage} · panel built {meta['built_at']} · "
        f"report generated {dt.datetime.now():%Y-%m-%d %H:%M} · internal use only (Bloomberg data)</p>",
        "<nav><a href='#summary'>Summary</a><a href='#panel'>Panel charts</a>"
        "<a href='#build'>Build checks</a>"
        "<a href='#foreign'>Foreign inputs</a><a href='#sa'>Seasonal adjustment</a>"
        "<a href='#raw'>Raw coverage</a><a href='#singstat'>SingStat</a>"
        "<a href='#anomalies'>Anomalies</a></nav>",
    ]

    status = (
        "<span class='ok'>none</span>"
        if unexplained.empty
        else f"<span class='flag'>{len(unexplained)}</span>"
    )
    parts.append(
        f"<h2 id='summary'>Summary</h2><p>{len(found)} anomalies (|z| &gt; {Z_OUTLIER:g}) across panel and "
        f"foreign series; unexplained: {status}; explained but still open: "
        f"<span class='flag'>{len(open_items)}</span>.</p><div class='wrap'>{table(summary)}</div>"
    )

    parts.append(
        "<h2 id='panel'>Panel charts</h2><p class='note'>Log-level columns are shown as annualised "
        "quarterly changes; red diamonds mark |z| &gt; 4.</p><div class='grid'>"
        + "".join(panel_chart(charts, panel, c) for c in COLUMNS)
        + "</div>"
    )

    ls_note = "; ".join(html.escape(t) for t in ls_rows["transform"])
    parts.append(
        "<h2 id='build'>Build checks</h2><div class='grid'>"
        + charts.line(rs_parts, "RS: SIBOR core with shifted IMF (before) and SORA (after)", "% p.a.")
        + charts.line(
            {"LS q/q, % p.a.": changes(panel["LS"].rename("LS")).loc[:"1999Q4"]},
            "LS around the 1994 BIS / IMF splice",
            "% p.a.",
        )
        + charts.line(csi, "CSI: blend, spread-only and NIM component", "pp of the spread")
        + charts.line(banks, "Bank NIM: T12 (primary) and company basis (post)", "%")
        + f"</div><p class='note'>LS lineage: {ls_note}</p>"
        + "<p>CSI stress-period check (P1.13a): mean in the stress window minus the mean over the four "
        + "quarters before it, pp (positive = tighter).</p>"
        + table(csi_stress(csi))
    )

    gaps = {k.removeprefix("GAP_"): v for k, v in foreign.items() if k.startswith("GAP_")}
    weights = pd.DataFrame(meta["weights"]).rename_axis("country").reset_index()
    pief = changes(panel["LCPIF"].rename("LCPIF"))
    parts.append(
        "<h2 id='foreign'>Foreign inputs (provisional until P3.7-P3.9)</h2><div class='grid'>"
        + charts.line(
            {"YF": panel["YF"]},
            "YF: export-weighted foreign output gap",
            "% of trend",
            panel["YF"].reindex(outliers(panel["YF"].rename("YF")).index),
        )
        + charts.line({"PIEF": pief}, "PIEF = 4 x d LCPIF", "% p.a.")
        + charts.line(dict(sorted(gaps.items())[:7]), "Country output gaps (HP 1600), first seven", "%")
        + charts.line(dict(sorted(gaps.items())[7:14]), "Country output gaps, next seven", "%")
        + "</div><p>Trade weights (omega = export shares for YF, xi = import shares for LCPIF):</p>"
        + f"<div class='wrap'>{table(weights)}</div>"
    )

    sa = pd.DataFrame(sorted(meta["seasonal_adjustment"].items()), columns=["ticker", "method"])
    parts.append(f"<h2 id='sa'>Seasonal adjustment</h2>{table(sa)}")

    cov = raw_coverage(manifest, vintage)
    parts.append(
        f"<h2 id='raw'>Raw series coverage ({len(cov)} registry series)</h2><p class='note'>"
        "Spans at native frequency; interior gaps = missing periods inside the span "
        "(monthly/quarterly only).</p><div class='wrap'>" + table(cov) + "</div>"
    )

    if crosschecks:
        cc = pd.read_csv(crosschecks[-1])
        cc = cc[
            ["table", "singstat", "ticker", "compare", "n", "first", "last", "mean_abs", "max_abs", "flag"]
        ]
        parts.append(
            f"<h2 id='singstat'>Bloomberg vs SingStat ({crosschecks[-1].stem})</h2><p class='note'>"
            "mean_abs / max_abs: % level gap or pp gap in period log change.</p>"
            f"<div class='wrap'>{table(cc.round(4))}</div>"
        )

    shown = found.assign(explanation=found["explanation"].fillna("UNEXPLAINED"))
    parts.append(f"<h2 id='anomalies'>Anomalies</h2><div class='wrap'>{table(shown)}</div>")

    page = (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
        f"content='width=device-width, initial-scale=1'><title>SMS data QA</title><style>{CSS}</style>"
        f"</head><body>{''.join(parts)}</body></html>"
    )
    return page, found


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the data QA report (P1.14).")
    parser.add_argument("--vintage", help="Bloomberg vintage (default: the panel's)")
    args = parser.parse_args(argv)
    page, found = build_report(args.vintage)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(page, encoding="utf-8")
    unexplained = found[found["explanation"].isna()]
    print(f"{len(found)} anomalies, {len(unexplained)} unexplained -> {REPORT_PATH}")
    if len(unexplained):
        print(unexplained.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
