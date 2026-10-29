"""Field investment intensity, not operating cost or individual well drilling cost."""
from io import BytesIO
from math import isfinite

import pandas as pd

from utils.benchmark import NEVER_DRILLED, yearly_long

BOE_PER_SM3 = 6.28981
METRICS = {
    "Cumulative investment": "investment_million",
    "Investment / recoverable boe": "per_recoverable_boe",
    "Investment / produced boe": "per_produced_boe",
    "Field investment / development well": "per_development_well_million",
    "Field investment / producer": "per_producer_million",
}


def prepare_investments(data, current_year):
    columns = ["fldName", "year", "nominal_mnok"]
    if data.empty:
        return pd.DataFrame(columns=columns)
    data = data.rename(columns={
        "prfInformationCarrier": "fldName", "prfYear": "year",
        "prfInvestmentsMillNOK": "nominal_mnok",
    })
    if not set(columns).issubset(data.columns):
        raise ValueError("Investment table needs field, year and investment in million NOK.")
    data = data[columns].copy()
    data["year"] = pd.to_numeric(data["year"], errors="coerce")
    data["nominal_mnok"] = pd.to_numeric(data["nominal_mnok"], errors="coerce")
    valid_year = data["year"].gt(0) & data["year"].mod(1).eq(0)
    valid_amount = data["nominal_mnok"].notna() & data["nominal_mnok"].abs().lt(float("inf"))
    if not (valid_year & valid_amount & data["fldName"].notna()).all():
        raise ValueError("Investment table contains missing or invalid fields, years or amounts.")
    data["year"] = data["year"].astype(int)
    if data.duplicated(["fldName", "year"]).any():
        raise ValueError("Investment table contains duplicate field/year rows.")
    return data.loc[data["year"] < current_year].sort_values(["fldName", "year"]).reset_index(drop=True)


def parse_price_index(content):
    data = pd.read_csv(BytesIO(content))
    if not {"year", "index"}.issubset(data.columns):
        raise ValueError("Inflation CSV must contain year,index columns.")
    data = data[["year", "index"]].apply(pd.to_numeric, errors="coerce")
    valid = (data.notna().all(axis=1) & data["year"].gt(0) & data["year"].lt(float("inf"))
             & data["year"].mod(1).eq(0) & data["index"].gt(0) & data["index"].lt(float("inf")))
    if not valid.all() or data.empty or data["year"].duplicated().any():
        raise ValueError("Inflation indices must be finite, positive and unique by whole calendar year.")
    return data.set_index(data["year"].astype(int))["index"]


def adjusted_investments(data, nok_per_unit=1.0, price_index=None, base_year=None):
    if not isfinite(nok_per_unit) or nok_per_unit <= 0:
        raise ValueError("FX rate must be a positive finite number of NOK per currency unit.")
    result = data.copy()
    factors = pd.Series(1.0, index=result.index)
    if price_index is not None:
        if base_year not in price_index.index:
            raise ValueError(f"Inflation index is missing the reference year {base_year}.")
        missing = sorted(set(result["year"]) - set(price_index.index))
        if missing:
            raise ValueError("Inflation index is missing investment years: " + ", ".join(map(str, missing)))
        factors = price_index.loc[base_year] / result["year"].map(price_index)
        if not (factors.gt(0) & factors.lt(float("inf"))).all():
            raise ValueError("Inflation adjustment factors must be positive and finite.")
    result["inflation_factor"] = factors
    result["nok_per_currency_unit"] = nok_per_unit
    result["investment_million"] = result["nominal_mnok"] * factors / nok_per_unit
    if not result["investment_million"].abs().lt(float("inf")).all():
        raise ValueError("Adjusted investment amounts exceed the supported numeric range.")
    return result


def benchmark_tables(annual, master, yearly, wells, cutoff):
    annual = annual.loc[annual["year"] <= cutoff].copy()
    annual = annual.sort_values(["fldName", "year"])
    annual["cumulative_million"] = annual.groupby("fldName")["investment_million"].cumsum()
    production = yearly_long(yearly)
    production = production.loc[production["year"] <= cutoff]
    annual = annual.merge(production[["fldName", "year", "oe"]], on=["fldName", "year"], how="left", validate="one_to_one")
    annual["per_annual_boe"] = annual["investment_million"].div(annual["oe"].where(annual["oe"] > 0) * BOE_PER_SM3)
    grouped = annual.groupby("fldName")
    summary = pd.DataFrame(index=master.index)
    summary["investment_million"] = grouped["investment_million"].sum(min_count=1)
    summary["investment_first_year"] = grouped["year"].min()
    summary["investment_last_year"] = grouped["year"].max()
    summary["investment_years"] = grouped.size()
    summary["missing_investment_years"] = (
        summary["investment_last_year"] - summary["investment_first_year"] + 1 - summary["investment_years"]
    )
    summary["produced_oe_through_cutoff"] = production.groupby("fldName")["oe"].sum(min_count=1)
    summary["recoverable_oe_latest"] = master["recoverable_oe"]
    if not wells.empty:
        completed = wells.loc[
            ~wells["wlbStatus"].isin(NEVER_DRILLED) & wells["wlbCompletionYear"].le(cutoff)
        ]
        summary["development_wells_through_cutoff"] = completed.groupby("wlbField").size()
        summary["producers_through_cutoff"] = completed.loc[
            completed["wlbPurpose"].eq("PRODUCTION")
        ].groupby("wlbField").size()
    else:
        summary["development_wells_through_cutoff"] = float("nan")
        summary["producers_through_cutoff"] = float("nan")
    for metric, denominator, multiplier in (
        ("per_recoverable_boe", "recoverable_oe_latest", BOE_PER_SM3),
        ("per_produced_boe", "produced_oe_through_cutoff", BOE_PER_SM3),
        ("per_development_well_million", "development_wells_through_cutoff", 1),
        ("per_producer_million", "producers_through_cutoff", 1),
    ):
        summary[metric] = summary["investment_million"].div(
            summary[denominator].where(summary[denominator] > 0) * multiplier
        )
    summary["cutoff_year"] = cutoff
    return summary, annual
