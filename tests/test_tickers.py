"""Ticker registry loader (P1.6b). Runs against the committed config/tickers.yaml (no Bloomberg data)."""

import pytest

from data.tickers import (
    RegistryError,
    consensus_tickers,
    expand_template,
    select,
    series,
    singapore_consensus_tickers,
)


def test_registry_loads_and_validates():
    df = series()
    assert len(df) > 150
    assert df["ticker"].notna().all()
    assert set(df["section"]) == {"singapore", "trade", "united_states", "foreign"}


def test_one_primary_per_domestic_observable():
    # CSI is a blend (D3) with several primary components; the other five have exactly one.
    for var, ticker in [("LGDP", "SGDSTOTL Index"), ("LCPI", "SICPISA Index"), ("UNR", "SIQUTOTA Index"),
                        ("RS", "SIBF3M Index"), ("LS", "NBISSING Index")]:
        assert select(var=var, role="primary")["ticker"].tolist() == [ticker]


def test_defaults_filled():
    df = series()
    assert select(var="LGDP", role="primary")["field"].item() == "PX_LAST"
    nim = select(group="csi_net_interest_margin", role="primary")
    assert set(nim["field"]) == {"T12_NET_INT_MARGIN"}
    assert select(group="total_exports_by_partner", country="SG", role="primary")["partner"].nunique() == 20
    assert df.loc[df["ticker"] == "SIEXTOPH Index", "status"].item() == "gap"
    assert df.loc[df["ticker"] == "SGDSTOTL Index", "status"].item() == "verified"
    assert df["var"].ne("none").all()


def test_foreign_rows_get_country_var_and_bloc():
    cn = select(section="foreign", country="CN")
    assert set(cn["var"]) == {"Y_CN", "LCPI_CN"} and set(cn["bloc"]) == {"CH"}
    ea7_cpi = select(section="foreign", bloc="EA7", group="cpi", role="primary")
    assert len(ea7_cpi) == 8


def test_select_accepts_lists():
    df = select(var=["LGDP", "LCPI"], role=["primary", "crosscheck"])
    assert set(df["var"]) == {"LGDP", "LCPI"}


def test_expand_template():
    assert expand_template("ECGD{cc} {yy} Index", 2026, "US") == "ECGDUS 26 Index"
    assert expand_template("ECGD{cc} {yy} Index", 2005, "JP") == "ECGDJP 05 Index"
    assert expand_template("ECPISG {yy} Index", 14) == "ECPISG 14 Index"


def test_consensus_tickers():
    df = consensus_tickers(2026)
    assert (df["kind"] == "gdp").sum() == (df["kind"] == "cpi").sum() == 21
    assert df.loc[df["kind"] == "policy_rate", "ticker"].tolist() == ["ECPOUS 26 Index"]
    assert consensus_tickers(2026, kinds="gdp")["kind"].eq("gdp").all()
    assert singapore_consensus_tickers(2014) == ["ECGDSG 14 Index", "ECPISG 14 Index", "ECCXSG 14 Index"]


@pytest.mark.parametrize("entry, message", [
    ({"ticker": "X Index", "role": "main"}, "role='main'"),
    ({"ticker": "X Index", "form": "pct"}, "form='pct'"),
    ({"var": "LGDP"}, "no ticker"),
])
def test_validate_rejects_bad_entries(entry, message):
    registry = {"singapore": {"gdp": [entry]}}
    with pytest.raises(RegistryError, match=message):
        series(registry)


def test_validate_rejects_duplicates():
    entry = {"ticker": "X Index", "var": "LGDP"}
    with pytest.raises(RegistryError, match="duplicate entry X Index"):
        series({"singapore": {"gdp": [entry, entry]}})
