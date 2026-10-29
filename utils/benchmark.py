"""Field benchmarking: master table, normalised production profiles, envelopes and comparisons.

Units follow SODIR: oil / NGL / condensate / water in million Sm3, gas in billion Sm3,
oil equivalent (o.e.) in million Sm3 o.e. (1 billion Sm3 gas = 1 million Sm3 o.e.).
"""
from io import BytesIO
import re

import numpy as np
import pandas as pd

from utils.data import YEARLY_COLUMNS, latest_per_field

PRODUCTS = {"Oil equivalent": "oe", "Oil": "oil", "Gas": "gas"}
PRODUCT_UNITS = {"oe": "million Sm³ o.e.", "oil": "million Sm³", "gas": "billion Sm³"}
BASES = {
    "Annual volume": "absolute",
    "Per producing well": "per_well",
    "% of recoverable (reserve intensity)": "pct_recoverable",
    "% of in-place volume": "pct_inplace",
}
ACTIVE_STATUSES = {"PRODUCING", "INJECTING", "ONLINE/OPERATIONAL", "PRODUCING/INJECTING"}
NEVER_DRILLED = {"WILL NEVER BE DRILLED", "PREDRILLED"}
COLOR_OPTIONS = {
    "HC type": "hc_type", "Drainage strategy": "drainage_strategy", "Area": "area",
    "Main group": "main_group", "Main formation": "main_formation", "Lithology": "main_lithology",
    "Age": "main_age", "Status": "status", "Development concept": "main_concept",
    "Development type": "development_type", "HPHT": "hpht_label",
}
FACT_LIST_COLUMNS = ("formations", "groups", "ages", "lithology", "mechanisms", "concept")
PRODUCTION_SUMMARY_COLUMNS = (
    "start_year", "first_reported_year", "last_year", "cum_oil", "cum_gas", "cum_ngl", "cum_condensate", "cum_oe",
    "cum_water", "peak_oe", "peak_year", "years_on_production", "years_to_peak",
)
WELL_SUMMARY_COLUMNS = (
    "wells_drilled", "producers_drilled", "injectors_drilled", "observation_wells", "producers_active",
    "injectors_active", "subsea_share", "multilateral_share", "median_td_m", "median_tvd_m", "first_well_year",
    "last_well_year", "injector_producer_ratio",
)
FACT_SCALAR_COLUMNS = (
    "drainage_strategy", "main_formation", "main_group", "main_age", "main_lithology", "depth_min_m", "depth_max_m",
    "depth_mid_m", "water_depth_min_m", "water_depth_max_m", "hpht", "sub_area", "discovery_year", "pdo_year",
    "production_start_text", "producers_text", "injectors_text", "well_slots_text", "rf_initial_text",
    "rf_expected_text", "reservoir_quality", "gas_lift", "development_phases", "shutdown_year",
    "pressure_bar_text", "temperature_c_text", "pressure_bar", "temperature_c", "pt_confidence", "pt_source",
)


def yearly_long(yearly):
    data = yearly.rename(columns=YEARLY_COLUMNS).rename(columns={"prfInformationCarrier": "fldName", "prfYear": "year"})
    keep = ["fldName", "year"] + list(YEARLY_COLUMNS.values())
    return data[[c for c in keep if c in data]].copy()


_yearly_long = yearly_long


def production_summary(yearly, current_year=None, start_threshold=0.0):
    """Per field: first/last producing year, cumulative volumes, peak o.e. and its timing.

    `start_threshold` (fraction of the field's peak annual o.e.) lets the start year skip
    test or pre-start volumes, e.g. 0.05 = first year at or above 5% of peak.
    """
    data = _yearly_long(yearly)
    if data.empty:
        return pd.DataFrame()
    producing = data.loc[data["oe"].fillna(0) > 0]
    if current_year is not None:
        producing = producing.loc[producing["year"] < current_year]
    grouped = producing.groupby("fldName")
    peak = grouped["oe"].transform("max")
    meaningful = producing.loc[producing["oe"] >= start_threshold * peak] if start_threshold else producing
    summary = pd.DataFrame({
        "start_year": meaningful.groupby("fldName")["year"].min(),
        "first_reported_year": grouped["year"].min(),
        "last_year": grouped["year"].max(),
        "cum_oil": grouped["oil"].sum(min_count=1),
        "cum_gas": grouped["gas"].sum(min_count=1),
        "cum_ngl": grouped["ngl"].sum(min_count=1),
        "cum_condensate": grouped["condensate"].sum(min_count=1),
        "cum_oe": grouped["oe"].sum(min_count=1),
        "cum_water": grouped["water"].sum(min_count=1),
        "peak_oe": grouped["oe"].max(),
    })
    peak_year = producing.loc[producing.groupby("fldName")["oe"].idxmax(), ["fldName", "year"]].set_index("fldName")["year"]
    summary["peak_year"] = peak_year
    summary["years_on_production"] = summary["last_year"] - summary["start_year"] + 1
    summary["years_to_peak"] = summary["peak_year"] - summary["start_year"] + 1
    return summary


def well_summary(wells):
    """Per field: drilled / active producers and injectors, subsea and multilateral shares, depths."""
    if wells is None or wells.empty:
        return pd.DataFrame()
    data = wells.loc[~wells["wlbStatus"].isin(NEVER_DRILLED) & wells["wlbField"].notna()].copy()
    data["is_producer"] = data["wlbPurpose"].eq("PRODUCTION")
    data["is_injector"] = data["wlbPurpose"].str.startswith("INJECTION", na=False)
    data["is_observation"] = data["wlbPurpose"].eq("OBSERVATION")
    data["active"] = data["wlbStatus"].isin(ACTIVE_STATUSES)
    grouped = data.groupby("wlbField")
    summary = pd.DataFrame({
        "wells_drilled": grouped.size(),
        "producers_drilled": grouped["is_producer"].sum(),
        "injectors_drilled": grouped["is_injector"].sum(),
        "observation_wells": grouped["is_observation"].sum(),
        "producers_active": grouped.apply(lambda g: int((g["is_producer"] & g["active"]).sum()), include_groups=False),
        "injectors_active": grouped.apply(lambda g: int((g["is_injector"] & g["active"]).sum()), include_groups=False),
        "subsea_share": grouped["wlbSubSea"].apply(lambda s: float(s.eq("YES").mean()) if len(s) else np.nan),
        "multilateral_share": grouped["wlbMultilateral"].apply(lambda s: float(s.astype("string").str.upper().eq("YES").mean()) if len(s) else np.nan),
        "median_td_m": grouped["wlbTotalDepth"].median(),
        "median_tvd_m": grouped["wlbFinalVerticalDepth"].median(),
        "first_well_year": grouped["wlbCompletionYear"].min(),
        "last_well_year": grouped["wlbCompletionYear"].max(),
    })
    summary.index.name = "fldName"
    summary["injector_producer_ratio"] = summary["injectors_drilled"].div(summary["producers_drilled"].where(summary["producers_drilled"] > 0))
    return summary


def producers_by_year(wells, current_year):
    """Long table (fldName, year, producers): production wells completed and not yet plugged.

    Wells without a plugged date stay counted until `current_year`, so late-life counts
    can be conservative (high) for fields with many unreported abandonments.
    """
    if wells is None or wells.empty:
        return pd.DataFrame(columns=["fldName", "year", "producers"])
    data = wells.loc[
        wells["wlbPurpose"].eq("PRODUCTION") & ~wells["wlbStatus"].isin(NEVER_DRILLED | {"JUNKED"})
        & wells["wlbCompletionYear"].notna() & wells["wlbField"].notna()
    ]
    end = data["plugged_year"].fillna(current_year).clip(upper=current_year)
    start = data["wlbCompletionYear"].astype(int)
    records = []
    for field, first, last in zip(data["wlbField"], start, end):
        if last >= first:
            records.append(pd.DataFrame({"fldName": field, "year": np.arange(first, int(last) + 1)}))
    if not records:
        return pd.DataFrame(columns=["fldName", "year", "producers"])
    counts = pd.concat(records).groupby(["fldName", "year"]).size().rename("producers").reset_index()
    return counts


def build_master(overview, reserves, inplace, yearly, wells, facts, pt=None, current_year=None, start_threshold=0.0):
    """One row per field combining SODIR tables, well counts and text-derived facts."""
    base = latest_per_field(overview) if overview is not None and not overview.empty else pd.DataFrame()
    master = pd.DataFrame(index=base.index)
    master.index.name = "fldName"
    master["hc_type"] = base.get("fldHcType", pd.Series(dtype=object)).astype("string").str.upper()
    master["area"] = base.get("fldMainArea", pd.Series(dtype=object)).astype("string").str.upper()
    master["status"] = base.get("fldCurrentActivitySatus", pd.Series(dtype=object))
    master["operator"] = base.get("cmpLongName", pd.Series(dtype=object))
    master["discovery_well"] = base.get("wlbName", pd.Series(dtype=object))

    latest_reserves = latest_per_field(reserves) if reserves is not None and not reserves.empty else pd.DataFrame()
    for product in ("Oil", "Gas", "NGL", "Condensate", "OE"):
        for kind in ("Recoverable", "Remaining"):
            column = f"fld{kind}{product}"
            master[f"{kind.lower()}_{product.lower()}"] = pd.to_numeric(
                latest_reserves.get(column, pd.Series(dtype=float)), errors="coerce"
            ).reindex(master.index)

    latest_inplace = latest_per_field(inplace) if inplace is not None and not inplace.empty else pd.DataFrame()
    for name, column in (("inplace_oil", "fldInplaceOil"), ("inplace_free_gas", "fldInplaceFreeGas"),
                         ("inplace_ass_gas", "fldInplaceAssGas"), ("inplace_ass_liquid", "fldInplaceAssLiquid")):
        master[name] = pd.to_numeric(latest_inplace.get(column, pd.Series(dtype=float)), errors="coerce").reindex(master.index)
    master["inplace_gas"] = master[["inplace_free_gas", "inplace_ass_gas"]].sum(axis=1, min_count=1)
    master["inplace_oe"] = master[["inplace_oil", "inplace_gas", "inplace_ass_liquid"]].sum(axis=1, min_count=1)

    production = production_summary(yearly, current_year, start_threshold) if yearly is not None and not yearly.empty else pd.DataFrame()
    master = master.join(production, how="left")
    master = master.join(well_summary(wells), how="left")
    for column in PRODUCTION_SUMMARY_COLUMNS + WELL_SUMMARY_COLUMNS:
        if column not in master:
            master[column] = np.nan

    if facts is not None and not facts.empty:
        keep = [c for c in facts.columns if c not in ("text_length",)]
        master = master.join(facts[keep], how="left")
    for column in FACT_LIST_COLUMNS:
        if column not in master:
            master[column] = None
        master[column] = master[column].apply(lambda v: v if isinstance(v, list) else [])
        master[f"{column}_text"] = master[column].apply(", ".join)
    if pt is not None and not pt.empty:
        master = master.join(pt[["pressure_bar", "temperature_c", "confidence", "source"]].rename(
            columns={"confidence": "pt_confidence", "source": "pt_source"}), how="left")
    for column in FACT_SCALAR_COLUMNS:
        if column not in master:
            master[column] = np.nan
    master["main_concept"] = master["concept"].apply(lambda v: v[0] if v else None)
    master["hpht_label"] = master.get("hpht_status", pd.Series(index=master.index, dtype="string")).fillna("Not stated")
    if "development_type" not in master:
        master["development_type"] = "Not stated"

    master["rf_oil"] = master["recoverable_oil"].div(master["inplace_oil"].where(master["inplace_oil"] > 0))
    master["rf_gas"] = master["recoverable_gas"].div(master["inplace_gas"].where(master["inplace_gas"] > 0))
    master["rf_oe"] = master["recoverable_oe"].div(master["inplace_oe"].where(master["inplace_oe"] > 0))
    # SODIR books condensate as recoverable oil for some gas fields while in-place oil excludes it;
    # keep the raw ratio for audit and blank out physically impossible recovery factors.
    for product in ("oil", "gas", "oe"):
        raw = master[f"rf_{product}"]
        master[f"rf_{product}_raw"] = raw
        master[f"rf_{product}"] = raw.where(raw <= 1.0)
    master["produced_share_oe"] = master["cum_oe"].div(master["recoverable_oe"].where(master["recoverable_oe"] > 0))
    master["peak_offtake_pct"] = 100 * master["peak_oe"].div(master["recoverable_oe"].where(master["recoverable_oe"] > 0))
    master["reserves_per_producer"] = master["recoverable_oe"].div(master["producers_drilled"].where(master["producers_drilled"] > 0))
    master["inplace_per_producer"] = master["inplace_oe"].div(master["producers_drilled"].where(master["producers_drilled"] > 0))
    master["cum_water_cut"] = master["cum_water"].div((master["cum_water"] + master["cum_oil"]).where(lambda s: s > 0))
    for column in ("drainage_strategy",):
        master[column] = master[column].fillna("Not stated")
    for column in ("hc_type", "area"):
        master[column] = master[column].fillna("Unknown")
    return master


def apply_filters(master, hc_types=None, areas=None, drives=None, formations=None, groups=None,
                  statuses=None, inplace_range=None, recoverable_range=None, start_range=None,
                  min_years=0, hpht=None, lithologies=None, include_missing=True):
    """Boolean mask over the master table for the sidebar filters (None = no filter)."""
    mask = pd.Series(True, index=master.index)
    if hc_types:
        mask &= master["hc_type"].isin(hc_types)
    if areas:
        mask &= master["area"].isin(areas)
    if drives:
        mask &= master["drainage_strategy"].isin(drives)
    if statuses:
        mask &= master["status"].isin(statuses)
    if formations and "formations" in master:
        wanted = {f.lower() for f in formations}
        mask &= master["formations"].apply(lambda v: any(x.lower() in wanted for x in v))
    if groups and "groups" in master:
        wanted = {g.lower() for g in groups}
        mask &= master["groups"].apply(lambda v: any(x.lower() in wanted for x in v))
    if lithologies and "lithology" in master:
        wanted = {g.lower() for g in lithologies}
        mask &= master["lithology"].apply(lambda v: any(x.lower() in wanted for x in v))
    if inplace_range is not None:
        low, high = inplace_range
        within = master["inplace_oe"].between(low, high)
        if include_missing:
            within |= master["inplace_oe"].isna()
        mask &= within
    if recoverable_range is not None:
        low, high = recoverable_range
        within = master["recoverable_oe"].between(low, high)
        if include_missing:
            within |= master["recoverable_oe"].isna()
        mask &= within
    if start_range is not None:
        low, high = start_range
        mask &= master["start_year"].between(low, high)
    if min_years:
        mask &= master["years_on_production"].fillna(0) >= min_years
    if hpht is not None and "hpht_label" in master:
        mask &= master["hpht_label"].eq("HPHT (stated)" if hpht else "Non-HPHT (stated)")
    return mask


def normalised_profiles(yearly, master, product="oe", basis="absolute", wells=None, current_year=None,
                        fields=None):
    """Long table of annual values per field, normalised per `basis`, with years since start.

    basis: absolute | per_well | pct_recoverable | pct_inplace
    """
    data = _yearly_long(yearly)
    if fields is not None:
        data = data.loc[data["fldName"].isin(fields)]
    if current_year is not None:
        data = data.loc[data["year"] < current_year]
    data = data.loc[data["oe"].fillna(0) > 0].copy()
    starts = master["start_year"].dropna()
    data["start_year"] = data["fldName"].map(starts)
    data = data.dropna(subset=["start_year"]).copy()
    data["years_on"] = (data["year"] - data["start_year"] + 1).astype(int)
    data = data.loc[data["years_on"] >= 1]
    data["raw"] = data[product]
    if basis == "absolute":
        data["value"] = data["raw"]
    elif basis == "per_well":
        counts = producers_by_year(wells, current_year or int(data["year"].max()) + 1)
        data = data.merge(counts, on=["fldName", "year"], how="left")
        data["value"] = data["raw"].div(data["producers"].where(data["producers"] > 0))
    elif basis == "pct_recoverable":
        column = {"oe": "recoverable_oe", "oil": "recoverable_oil", "gas": "recoverable_gas"}[product]
        denominator = master[column].where(master[column] > 0)
        data["value"] = 100 * data["raw"].div(data["fldName"].map(denominator))
    elif basis == "pct_inplace":
        column = {"oe": "inplace_oe", "oil": "inplace_oil", "gas": "inplace_gas"}[product]
        denominator = master[column].where(master[column] > 0)
        data["value"] = 100 * data["raw"].div(data["fldName"].map(denominator))
    else:
        raise ValueError(f"Unknown basis {basis}")
    return data.dropna(subset=["value"]).sort_values(["fldName", "year"]).reset_index(drop=True)


def envelope(profiles, min_fields=3):
    """P10 / P50 / P90 / mean of `value` by years since start (P90 = high case)."""
    if profiles.empty:
        return pd.DataFrame(columns=["years_on", "p10", "p50", "p90", "mean", "n"])
    grouped = profiles.groupby("years_on")["value"]
    table = pd.DataFrame({
        "p10": grouped.quantile(0.10), "p50": grouped.median(), "p90": grouped.quantile(0.90),
        "mean": grouped.mean(), "n": grouped.size(),
    })
    return table.loc[table["n"] >= min_fields].reset_index()


def ratios(yearly, master, current_year=None, fields=None):
    """GOR (Sm3/Sm3), water cut and gas share of o.e. by field and year."""
    data = _yearly_long(yearly)
    if fields is not None:
        data = data.loc[data["fldName"].isin(fields)]
    if current_year is not None:
        data = data.loc[data["year"] < current_year]
    data = data.loc[data["oe"].fillna(0) > 0].copy()
    data["start_year"] = data["fldName"].map(master["start_year"].dropna())
    data = data.dropna(subset=["start_year"]).copy()
    data["years_on"] = (data["year"] - data["start_year"] + 1).astype(int)
    data = data.loc[data["years_on"] >= 1]
    oil = data["oil"].where(data["oil"] > 0)
    data["gor"] = 1000 * data["gas"].div(oil)                 # billion/million -> Sm3/Sm3
    liquid = data["water"] + data["oil"]
    data["water_cut"] = data["water"].div(liquid.where(liquid > 0))
    data["gas_share"] = data["gas"].div(data["oe"].where(data["oe"] > 0))
    data["cgr"] = data["condensate"].div(data["gas"].where(data["gas"] > 0))  # million Sm3 per billion Sm3
    return data


COLUMN_ALIASES = {
    "year": ("year", "yr", "prfyear", "date", "calendar year"),
    "oil": ("oil", "oil_mill_sm3", "oil mill sm3", "oil (million sm3)", "oil_msm3", "prfprdoilnetmillsm3", "oil_mmsm3"),
    "gas": ("gas", "gas_bill_sm3", "gas (billion sm3)", "gas_gsm3", "prfprdgasnetbillsm3", "gas_bsm3"),
    "ngl": ("ngl", "prfprdnglnetmillsm3"),
    "condensate": ("condensate", "cond", "prfprdcondensatenetmillsm3"),
    "water": ("water", "produced water", "water_mill_sm3", "prfprdproducedwaterinfieldmillsm3"),
    "oe": ("oe", "o.e.", "oil equivalent", "boe", "prfprdoenetmillsm3", "oil_equivalent"),
    "wells": ("wells", "producers", "producing wells", "active producers", "n_wells"),
}


def parse_profile_upload(content, filename="profile.csv"):
    """Read a user profile (CSV / Excel) with flexible column names into year/oil/gas/.../oe."""
    raw = BytesIO(content) if isinstance(content, (bytes, bytearray)) else content
    if str(filename).lower().endswith((".xlsx", ".xls", ".xlsm")):
        table = pd.read_excel(raw)
    else:
        table = pd.read_csv(raw, sep=None, engine="python")
    lookup = {re.sub(r"\s+", " ", str(c).strip().lower()): c for c in table.columns}
    renamed = {}
    for target, names in COLUMN_ALIASES.items():
        for name in names:
            if name in lookup and lookup[name] not in renamed:
                renamed[lookup[name]] = target
                break
    table = table.rename(columns=renamed)
    if "year" not in table:
        raise ValueError("The profile needs a 'year' column.")
    for column in ("oil", "gas", "ngl", "condensate", "water", "oe", "wells"):
        table[column] = pd.to_numeric(table.get(column), errors="coerce") if column in table else np.nan
    table["year"] = pd.to_numeric(table["year"], errors="coerce")
    table = table.dropna(subset=["year"]).copy()
    table["year"] = table["year"].astype(int)
    if table["oe"].isna().all():
        table["oe"] = table[["oil", "gas", "ngl", "condensate"]].sum(axis=1, min_count=1)
    if table[["oil", "gas", "oe"]].isna().all().all():
        raise ValueError("The profile needs at least one of oil, gas or oil-equivalent columns.")
    keep = ["year", "oil", "gas", "ngl", "condensate", "water", "oe", "wells"]
    return table[keep].sort_values("year").reset_index(drop=True)


def normalise_upload(profile, product="oe", basis="absolute", recoverable=None, inplace=None):
    """Apply the same normalisation to a user profile; returns years_on / value columns."""
    data = profile.loc[profile["oe"].fillna(0) > 0].copy()
    if data.empty:
        return data.assign(years_on=[], value=[])
    data["years_on"] = data["year"] - data["year"].min() + 1
    data["raw"] = data[product]
    if basis == "absolute":
        data["value"] = data["raw"]
    elif basis == "per_well":
        data["value"] = data["raw"].div(data["wells"].where(data["wells"] > 0))
    elif basis == "pct_recoverable":
        data["value"] = 100 * data["raw"] / recoverable if recoverable else np.nan
    elif basis == "pct_inplace":
        data["value"] = 100 * data["raw"] / inplace if inplace else np.nan
    return data.dropna(subset=["value"])


def type_curve(env, recoverable, start_year, statistic="p50", basis="pct_recoverable", rescale=False):
    """Average profile scaled to a recoverable (or in-place) volume; values in product units per year.

    `rescale` forces the cumulative of the generated profile to equal `recoverable`
    (a median of yearly percentages does not sum to 100 % by construction).
    """
    if env.empty or not recoverable or recoverable <= 0:
        return pd.DataFrame(columns=["year", "years_on", "pct", "value", "cumulative"])
    table = env[["years_on", statistic]].rename(columns={statistic: "pct"}).copy()
    if basis in ("pct_recoverable", "pct_inplace"):
        if rescale and table["pct"].sum() > 0:
            table["pct"] = table["pct"] * 100 / table["pct"].sum()
        table["value"] = table["pct"] / 100 * recoverable
    else:
        table["value"] = table["pct"]
    table["year"] = start_year + table["years_on"] - 1
    table["cumulative"] = table["value"].cumsum()
    return table[["year", "years_on", "pct", "value", "cumulative"]]


def coverage(master, columns):
    """Share of fields with a non-null value per column (Data & QA)."""
    rows = []
    for column in columns:
        if column in master:
            series = master[column]
            if series.apply(lambda v: isinstance(v, list)).any():
                filled = series.apply(lambda v: bool(v) if isinstance(v, list) else pd.notna(v))
            else:
                filled = series.notna()
            rows.append(dict(attribute=column, fields_with_value=int(filled.sum()), share=float(filled.mean()) if len(filled) else 0.0))
    return pd.DataFrame(rows)
