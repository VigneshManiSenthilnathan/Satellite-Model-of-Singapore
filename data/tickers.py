"""Loader for the Bloomberg ticker registry, config/tickers.yaml (plan task P1.6b).

The registry is the only allowed source of tickers. This module flattens its
sections into one table, selects series by var/role/section/country, and
expands the year-rolling consensus templates.

Flattening rules for keys the YAML leaves implicit:
    field   -> meta.default_field (PX_LAST)
    role    -> "primary" (e.g. the SEMC*/SIMC* rows, whose crosscheck siblings say so)
    status  -> "verified"
    freq    -> trade rows: "M" (the registry's trade section is all monthly)
    var     -> foreign rows: Y_{country} for gdp, LCPI_{country} for cpi
               (same naming as the united_states section: Y_US, LCPI_US)

Usage:
    from data.tickers import select, consensus_tickers
    select(var="LGDP", role="primary")            # one-row DataFrame: SGDSTOTL Index
    select(section="foreign", group="cpi", role="primary").ticker.tolist()
    consensus_tickers(2026, kinds="gdp")          # ECGD{cc} 26 Index for every country
"""

from pathlib import Path

import pandas as pd
import yaml

TICKERS_PATH = Path(__file__).resolve().parent.parent / "config" / "tickers.yaml"

ROLES = {"primary", "history", "post", "crosscheck", "reference"}
FORMS = {"level", "index", "qoq", "qoq_saar", "yoy", "rate"}
FREQS = {"D", "M", "Q"}
STATUSES = {"verified", "check_units", "gap"}

COLUMNS = ["section", "group", "country", "bloc", "partner", "ticker", "field", "var", "role",
           "freq", "sa", "form", "span", "status", "break"]


class RegistryError(ValueError):
    """config/tickers.yaml is malformed."""


def load_registry(path=TICKERS_PATH):
    """Return the registry as the raw dict parsed from YAML."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _rows(registry):
    singapore = registry.get("singapore", {})
    for group, entries in singapore.items():
        for e in entries:
            if "template" not in e:
                yield {"section": "singapore", "group": group, "country": "SG", **e}
    for group, entries in registry.get("trade", {}).items():
        for e in entries:
            yield {"section": "trade", "group": group, "country": "SG", "var": None, **e}
    for e in registry.get("united_states", []):
        yield {"section": "united_states", "group": None, "country": "US", "bloc": "US", **e}
    for country, spec in registry.get("foreign", {}).items():
        for group in ("gdp", "cpi"):
            for e in spec.get(group, []):
                var = f"{'Y' if group == 'gdp' else 'LCPI'}_{country}"
                yield {"section": "foreign", "group": group, "country": country,
                       "bloc": spec.get("bloc"), "var": var, **e}


def series(registry=None):
    """Every ticker entry as one flat DataFrame (templates excluded), defaults filled."""
    registry = load_registry() if registry is None else registry
    df = pd.DataFrame(list(_rows(registry)), columns=COLUMNS, dtype=object)
    df["field"] = df["field"].fillna(registry.get("meta", {}).get("default_field", "PX_LAST"))
    df["role"] = df["role"].fillna("primary")
    df["status"] = df["status"].fillna("verified")
    df.loc[df["section"] == "trade", "freq"] = df.loc[df["section"] == "trade", "freq"].fillna("M")
    df["var"] = df["var"].replace("none", None)
    validate(df)
    return df


def validate(df):
    """Raise RegistryError listing every malformed entry."""
    problems = []
    if df["ticker"].isna().any():
        problems.append(f"{df['ticker'].isna().sum()} entries have no ticker")
    problems.extend(f"{t}: no freq" for t in df.loc[df["freq"].isna(), "ticker"])
    for col, allowed in (("role", ROLES), ("form", FORMS), ("freq", FREQS), ("status", STATUSES)):
        bad = df.loc[df[col].notna() & ~df[col].isin(allowed), ["ticker", col]]
        problems.extend(f"{t}: {col}={v!r} not in {sorted(allowed)}" for t, v in bad.itertuples(index=False))
    dupes = df[df.duplicated(["ticker", "field", "group"], keep=False)]
    problems.extend(f"duplicate entry {t} / {f}" for t, f in dupes[["ticker", "field"]].drop_duplicates()
                    .itertuples(index=False))
    if problems:
        raise RegistryError("config/tickers.yaml: " + "; ".join(problems))


def _as_set(value):
    return {value} if isinstance(value, str) else set(value)


def select(var=None, role=None, section=None, group=None, country=None, bloc=None, registry=None):
    """Filter the flat registry. Each argument takes a value or a list of values."""
    df = series(registry)
    for col, value in (("var", var), ("role", role), ("section", section), ("group", group),
                       ("country", country), ("bloc", bloc)):
        if value is not None:
            df = df[df[col].isin(_as_set(value))]
    return df.reset_index(drop=True)


def expand_template(template, year, cc=None):
    """Fill a "{cc}"/"{yy}" template, e.g. ("ECGD{cc} {yy} Index", 2026, "US") -> "ECGDUS 26 Index"."""
    return template.format(cc=cc, yy=f"{int(year) % 100:02d}")


def consensus_tickers(year, kinds=("gdp", "cpi", "policy_rate"), registry=None):
    """Bloomberg consensus (ECFC) tickers for one calendar year: DataFrame country, kind, ticker.

    policy_rate is only expanded for the registry's policy_rate_countries.
    """
    registry = load_registry() if registry is None else registry
    spec = registry["consensus"]
    rows = []
    for kind in _as_set(kinds):
        countries = spec["policy_rate_countries"] if kind == "policy_rate" else spec["countries"]
        rows += [(cc, kind, expand_template(spec["templates"][kind], year, cc)) for cc in countries]
    return pd.DataFrame(rows, columns=["country", "kind", "ticker"]).sort_values(
        ["kind", "country"], ignore_index=True)


def singapore_consensus_tickers(year, registry=None):
    """The singapore.consensus templates (GDP, headline and core CPI) for one calendar year."""
    registry = load_registry() if registry is None else registry
    templates = registry["singapore"].get("consensus", [])
    return [expand_template(e["template"], year) for e in templates]
