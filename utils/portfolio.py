"""Current-equity portfolio restatements, not historical company accounts."""
from io import BytesIO

import numpy as np
import pandas as pd
import streamlit as st

from utils import economics, ukcs
from utils.benchmark import yearly_long
from utils.investments import BOE_PER_SM3

NCS_EQUITY_SOURCE = "https://factpages.sodir.no/en/field/TableView/Licensees"
UK_REGIONS = ukcs.ROOT + "PDF_map_regions_(WGS84)/FeatureServer/0"
REGION_NAMES = {
    "NNS": "Northern North Sea", "CNS": "Central North Sea", "SNS": "Southern North Sea",
    "Irish_Sea": "Irish Sea", "WOS": "West of Shetland",
}
VOLUMES = ["oil", "gas", "condensate", "ngl", "oe"]
EQUITY_COLUMNS = ["fldName", "company", "company_name", "share", "equity_source", "snapshot_date"]


def ncs_equity(raw, snapshot):
    required = ["fldName", "cmpLongName", "cmpNpdidCompany", "fldCompanyShare",
                "fldOwnerFrom", "fldOwnerTo", "fldLicenseeFrom", "fldLicenseeTo"]
    if not set(required).issubset(raw):
        raise ValueError("SODIR equity history is missing required ownership columns.")
    data = raw.copy()
    day = pd.Timestamp(snapshot).normalize()
    active = pd.Series(True, index=data.index)
    for column in ("fldOwnerFrom", "fldOwnerTo", "fldLicenseeFrom", "fldLicenseeTo"):
        text = data[column].astype("string").str.strip()
        dates = pd.to_datetime(text, format="%d.%m.%Y", errors="coerce")
        if (text.notna() & text.ne("") & dates.isna()).any():
            raise ValueError(f"SODIR {column} contains invalid ownership dates.")
        if column.endswith("From"):
            active &= dates.notna() & dates.le(day)
        else:
            active &= dates.isna() | dates.ge(day)
    data = data.loc[active].copy()
    result = pd.DataFrame({
        "fldName": "NCS::" + data["fldName"].astype("string").str.strip().str.upper(),
        "company": "NCS::" + data["cmpNpdidCompany"].astype("string"),
        "company_name": data["cmpLongName"].astype("string").str.strip(),
        "share": pd.to_numeric(data["fldCompanyShare"], errors="raise") / 100,
        "equity_source": NCS_EQUITY_SOURCE, "snapshot_date": str(day.date()),
    })
    if data["cmpNpdidCompany"].isna().any():
        raise ValueError("SODIR equity records have missing company identifiers.")
    return result.reset_index(drop=True)


def uk_equity(features, snapshot):
    rows = []
    for feature in features:
        attributes = feature["attributes"]
        for number in range(1, 21):
            suffix = "" if number == 1 else str(number)
            company = str(attributes.get("CURRLIC" + suffix) or "").strip()
            percentage = attributes.get("EQUITY" + suffix)
            if not company and percentage in (None, 0):
                continue
            rows.append(dict(
                fldName=ukcs.field_key(attributes["FIELDNAME"]),
                company="UKCS::" + company.upper(), company_name=company or "Unnamed licensee",
                share=float(percentage) / 100 if percentage is not None and company else np.nan,
                equity_source=ukcs.FIELDS, snapshot_date=str(pd.Timestamp(snapshot).date()),
            ))
    return pd.DataFrame(rows, columns=EQUITY_COLUMNS)


def validate_equity(equity, fields):
    """Keep partial allocations as reported. Reject duplicate/overallocated field interests."""
    diagnostics, valid = [], []
    for field in fields.index:
        rows = equity.loc[equity["fldName"].eq(field)]
        total = rows["share"].sum(min_count=1)
        reason = ""
        if rows.empty:
            reason = "No current field equity records"
        elif not (np.isfinite(rows["share"]) & rows["share"].gt(0) & rows["share"].le(1)).all():
            reason = "Missing, zero or invalid licensee percentage"
        elif rows["company"].duplicated().any():
            reason = "Duplicate company interests require review"
        elif total > 1.000001:
            reason = "Reported shares exceed 100%; no allocation used"
        else:
            valid.append(rows)
        diagnostics.append(dict(
            fldName=field, reported_share_pct=100 * total if pd.notna(total) else np.nan,
            allocated_share_pct=0.0 if reason else 100 * total,
            unallocated_share_pct=100.0 if reason else max(0, 100 * (1 - total)),
            ownership_status=reason or ("Partial published equity; no renormalisation" if total < 0.999999 else "Allocated as published"),
        ))
    checked = pd.concat(valid, ignore_index=True) if valid else pd.DataFrame(columns=EQUITY_COLUMNS)
    return checked, pd.DataFrame(diagnostics).set_index("fldName")


def point_in_rings(point, rings):
    """Even/odd containment handles disjoint polygon parts and holes."""
    x, y = point
    inside = False
    for ring in rings:
        for left, right in zip(ring, ring[1:]):
            x1, y1 = left[:2]
            x2, y2 = right[:2]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def uk_regions(features, regions):
    classified = {}
    for feature in features:
        field = ukcs.field_key(feature["attributes"]["FIELDNAME"])
        centroid = feature.get("centroid") or {}
        if not {"x", "y"}.issubset(centroid):
            classified[field] = "Unclassified UK region"
            continue
        matches = []
        for region in regions:
            url = region["attributes"].get("LINKTOPROD", "")
            label = next((name for suffix, name in REGION_NAMES.items()
                          if url.endswith("_" + suffix + ".pdf")), None)
            if label and point_in_rings((centroid["x"], centroid["y"]), region["geometry"]["rings"]):
                matches.append(label)
        classified[field] = matches[0] if len(matches) == 1 else "Unclassified / overlapping UK map regions"
    return pd.Series(classified, name="region")


@st.cache_data(ttl=3600, show_spinner=False)
def load_uk_ownership():
    columns = ["FIELDNAME"]
    for number in range(1, 21):
        suffix = "" if number == 1 else str(number)
        columns.extend(["CURRLIC" + suffix, "EQUITY" + suffix])
    return ukcs.query(ukcs.FIELDS, outFields=",".join(columns), returnCentroid="true", outSR=4326)


@st.cache_data(ttl=86400, show_spinner=False)
def load_uk_region_polygons():
    return ukcs.query(UK_REGIONS, returnGeometry="true", outFields="LINKTOPROD", outSR=4326)


def field_metadata(overview, country):
    if country == "NCS":
        fields = overview.set_index("fldName")[["fldMainArea"]].rename(columns={"fldMainArea": "region"}).copy()
        fields["field_name"] = fields.index
        fields.index = "NCS::" + fields.index
        fields["production_basis"] = "SODIR reported OE and net products"
        fields["production_source"] = "https://factpages.sodir.no/en/field/TableView/Production"
    else:
        fields = overview.set_index("fldName")[["field_name"]].copy()
        fields["region"] = "Unclassified UK region"
        fields["production_basis"] = ukcs.PRODUCTION_BASIS
        fields["production_source"] = ukcs.PRODUCTION
    if not fields.index.is_unique:
        raise ValueError(f"{country} field catalogue has duplicate field identities.")
    fields.index.name = "fldName"
    fields["region"] = fields["region"].fillna("Unknown").astype(str)
    fields["country"] = country
    return fields


def field_history(yearly, costs, fields, current_year):
    production = yearly_long(yearly)
    production = production.loc[production["year"].lt(current_year), ["fldName", "year", *VOLUMES]]
    if production.duplicated(["fldName", "year"]).any():
        raise ValueError("Portfolio production contains duplicate field-year records.")
    annual = production.merge(costs, on=["fldName", "year"], how="outer", validate="one_to_one")
    annual = annual.loc[annual["fldName"].isin(fields.index)].copy()
    annual["year"] = annual["year"].astype(int)
    annual["production_mboe"] = annual["oe"] * BOE_PER_SM3
    annual["oil_mmbbl"] = annual["oil"] * BOE_PER_SM3
    annual["capex_source"] = np.where(annual["nominal_mnok"].notna(),
                                     "https://factpages.sodir.no/en/field/TableView/Investment", "")
    annual = annual.merge(fields.reset_index(), on="fldName", how="left", validate="many_to_one")
    return annual.sort_values(["fldName", "year"]).reset_index(drop=True)


def allocate(annual, equity):
    ledger = annual.merge(equity, on="fldName", how="inner", validate="many_to_many")
    for column in [*VOLUMES, "production_mboe", "oil_mmbbl", "nominal_mnok"]:
        if column in ledger:
            ledger[column] = ledger[column] * ledger["share"]
    return ledger


def company_annual(ledger):
    """Intensity uses identical asset-years on both sides, never a mean of field ratios."""
    columns = ["company", "company_name", "year", "production_mboe", "oil_mmbbl", *VOLUMES, "nominal_mnok",
               "matched_capex_mnok", "matched_production_mboe", "capex_nok_boe",
               "fields_with_production", "fields_with_capex", "matched_fields"]
    if ledger.empty:
        return pd.DataFrame(columns=columns)
    data = ledger.copy()
    for column in VOLUMES:
        if column not in data:
            data[column] = np.nan
    paired = data["production_mboe"].ge(0) & data["nominal_mnok"].notna()
    data["matched_capex_mnok"] = data["nominal_mnok"].where(paired)
    data["matched_production_mboe"] = data["production_mboe"].where(paired)
    group = ["company", "company_name", "year"]
    metrics = ["production_mboe", "oil_mmbbl", *VOLUMES, "nominal_mnok", "matched_capex_mnok", "matched_production_mboe"]
    result = data.groupby(group, dropna=False)[metrics].sum(min_count=1)
    for label, valid in (("fields_with_production", data["production_mboe"].notna()),
                         ("fields_with_capex", data["nominal_mnok"].notna()), ("matched_fields", paired)):
        result[label] = data.loc[valid].groupby(group)["fldName"].nunique().reindex(result.index, fill_value=0)
    result["capex_nok_boe"] = result["matched_capex_mnok"] / result["matched_production_mboe"].where(lambda v: v > 0)
    return result.reset_index()[columns]


def company_summary(annual):
    if annual.empty:
        return pd.DataFrame()
    totals = annual.groupby(["company", "company_name"])[
        ["production_mboe", "oil_mmbbl", *VOLUMES, "nominal_mnok", "matched_capex_mnok", "matched_production_mboe"]
    ].sum(min_count=1)
    totals["capex_nok_boe"] = totals["matched_capex_mnok"] / totals["matched_production_mboe"].where(lambda v: v > 0)
    totals["production_rank"] = totals["production_mboe"].rank(ascending=False, method="min").astype("Int64")
    return totals.reset_index().sort_values("production_mboe", ascending=False)


def parse_forecasts(content, filename, fields, cutoff, horizon):
    raw = pd.read_excel(BytesIO(content)) if filename.lower().endswith(".xlsx") else pd.read_csv(BytesIO(content))
    raw.columns = raw.columns.str.strip().str.lower()
    required = {"country", "field", "year", "oil", "gas", "condensate"}
    if raw.columns.duplicated().any() or not required.issubset(raw) or raw.empty:
        raise ValueError("Forecast upload needs unique country,field,year,oil,gas,condensate columns; NCS also needs ngl.")
    raw["fldName"] = raw["country"].astype(str).str.strip().str.upper() + "::" + raw["field"].astype(str).str.strip().str.upper()
    unknown = sorted(set(raw["fldName"]) - set(fields.index))
    if unknown:
        raise ValueError("Unknown field identities in upload: " + ", ".join(unknown))
    for column in ("year", "oil", "gas", "condensate"):
        raw[column] = pd.to_numeric(raw[column], errors="raise")
        if not (np.isfinite(raw[column]) & raw[column].ge(0)).all():
            raise ValueError(f"Forecast {column} must be finite, non-negative and not blank.")
    if not raw["year"].mod(1).eq(0).all() or raw.duplicated(["fldName", "year"]).any():
        raise ValueError("Forecasts need unique whole years per field.")
    raw["year"] = raw["year"].astype(int)
    if "ngl" not in raw:
        raw["ngl"] = np.nan
    raw["ngl"] = pd.to_numeric(raw["ngl"], errors="raise")
    ncs = raw["fldName"].str.startswith("NCS::")
    if not (np.isfinite(raw.loc[ncs, "ngl"]) & raw.loc[ncs, "ngl"].ge(0)).all():
        raise ValueError("Every NCS forecast year needs a finite non-negative ngl volume.")
    if raw.loc[~ncs, "ngl"].notna().any():
        raise ValueError("UK forecasts must leave ngl blank to retain the pipeline-gas/no-separate-NGL comparison basis.")
    required_years = set(range(cutoff + 1, cutoff + horizon + 1))
    for field, part in raw.groupby("fldName"):
        if set(part["year"]) != required_years:
            raise ValueError(f"{field}: upload must cover every year {cutoff + 1}–{cutoff + horizon}. Use explicit zeros for cessation.")
    raw["oe"] = raw["oil"] + raw["gas"] + raw["condensate"] + 1.9 * raw["ngl"].fillna(0)
    raw["method"] = "Uploaded field forecast"
    return raw[["fldName", "year", *VOLUMES, "method"]].sort_values(["fldName", "year"])


def forecast_fields(history, fields, cutoff, horizon, overrides=None, main_phase=None):
    forecasts, diagnostics = [], []
    for field in fields.index:
        data = history.loc[history["fldName"].eq(field) & history["year"].le(cutoff)].copy()
        upload = overrides.loc[overrides["fldName"].eq(field)] if overrides is not None else pd.DataFrame()
        try:
            if not upload.empty:
                future = upload.copy()
                method, detail = "Uploaded field forecast", "Complete horizon overrides fitted forecast"
            else:
                if data.empty:
                    raise ValueError("No production history at the selected cutoff")
                columns = ["year", "oil", "gas", "condensate"]
                if fields.loc[field, "country"] == "NCS":
                    columns.append("ngl")
                window = data.loc[data["year"].ge(cutoff - 4), columns]
                future, fit = economics.fitted_forecast(window, cutoff, horizon, main_phase=main_phase)
                if fields.loc[field, "country"] == "UKCS":
                    future["ngl"] = np.nan
                phase = fit.iloc[0]["main_phase"]
                method = "Fitted main phase; fixed product ratios"
                decline = fit.loc[fit["product"].eq(phase), "effective_decline_pct"].iloc[0]
                detail = f"{phase}; annual effective decline {decline:.2f}%; {int(fit.iloc[0]['observations'])} observations"
                future["method"] = method
            future["fldName"] = field
            future["production_mboe"] = future["oe"] * BOE_PER_SM3
            future["oil_mmbbl"] = future["oil"] * BOE_PER_SM3
            forecasts.append(future[["fldName", "year", *VOLUMES, "production_mboe", "oil_mmbbl", "method"]])
            status = "Included"
        except ValueError as exc:
            method, detail, status = "Not forecast", str(exc), "Excluded"
        diagnostics.append(dict(fldName=field, forecast_status=status, method=method, forecast_detail=detail))
    result = pd.concat(forecasts, ignore_index=True) if forecasts else pd.DataFrame(
        columns=["fldName", "year", *VOLUMES, "production_mboe", "oil_mmbbl", "method"])
    result = result.merge(fields.reset_index(), on="fldName", how="left", validate="many_to_one")
    return result, pd.DataFrame(diagnostics).set_index("fldName")


def forecast_companies(forecasts, history, equity, cutoff):
    ledger = allocate(forecasts, equity)
    if ledger.empty:
        return pd.DataFrame(), ledger
    keys = ["company", "company_name", "year"]
    result = ledger.groupby(keys)[["production_mboe", "oil_mmbbl"]].sum(min_count=1).reset_index()
    forecast_ids = set(forecasts["fldName"])
    baseline = allocate(history.loc[history["year"].eq(cutoff) & history["fldName"].isin(forecast_ids)], equity)
    base = baseline.groupby("company")["production_mboe"].sum(min_count=1)
    covered = baseline.loc[baseline["production_mboe"].notna()].groupby("company")["fldName"].nunique()
    expected = ledger.groupby("company")["fldName"].nunique()
    base = base.where(covered.reindex(base.index).eq(expected.reindex(base.index)))
    result["matched_cutoff_mboe"] = result["company"].map(base)
    all_baseline = allocate(history.loc[history["year"].eq(cutoff)], equity)
    reported = all_baseline.groupby("company")["production_mboe"].sum(min_count=1)
    result["reported_cutoff_mboe"] = result["company"].map(reported)
    result["forecast_baseline_coverage_pct"] = (
        100 * result["matched_cutoff_mboe"] / result["reported_cutoff_mboe"].where(lambda v: v > 0)
    )
    result["forecast_field_count"] = result["company"].map(expected)
    result["production_index"] = 100 * result["production_mboe"] / result["matched_cutoff_mboe"].where(lambda v: v > 0)
    return result, ledger
