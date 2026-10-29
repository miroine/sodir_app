"""Source-linked reservoir observations; no estimated values for missing literature facts."""
from pathlib import Path
from io import BytesIO
import re

import pandas as pd
import numpy as np

from utils.pt import estimate_from_depth, load_curated

PATH = Path(__file__).resolve().parents[1] / "data" / "reservoir_parameters.csv"
COLUMNS = [
    "field", "parameter", "value_min", "value_max", "unit", "reservoir",
    "conditions", "evidence_status", "source_title", "source_url", "evidence_url", "source_locator", "reviewed_date",
]
COMBINED_COLUMNS = COLUMNS + ["dataset", "quality", "well"]
UPLOAD_REQUIRED = ["field", "parameter", "value_min", "unit", "reservoir", "conditions",
                   "source_title", "source_url", "source_locator"]


def parse_observation_upload(content, filename, known_fields):
    raw = BytesIO(content)
    table = pd.read_excel(raw, keep_default_na=False) if filename.lower().endswith(".xlsx") else pd.read_csv(raw, keep_default_na=False)
    table.columns = table.columns.str.strip().str.lower()
    if table.columns.duplicated().any() or not set(UPLOAD_REQUIRED).issubset(table.columns):
        raise ValueError("Use unique columns and include: " + ", ".join(UPLOAD_REQUIRED))
    if table.empty:
        raise ValueError("The uploaded observation table is empty.")
    for column in COLUMNS:
        if column not in table:
            table[column] = ""
        table[column] = table[column].astype(str).str.strip()
    for column in UPLOAD_REQUIRED:
        if table[column].eq("").any():
            raise ValueError(f"Uploaded observations have blank {column}.")
        if table[column].str.startswith("REPLACE with").any():
            raise ValueError("Replace the illustrative template placeholders with your source observations.")
    table["field"] = table["field"].str.upper()
    unknown = sorted(set(table["field"]) - {str(name).strip().upper() for name in known_fields})
    if unknown:
        raise ValueError("Unmatched field names: " + ", ".join(unknown))
    if not table["source_url"].str.match(r"^https://[^\s/]+\.[^\s]+$").all():
        raise ValueError("Each observation requires a valid HTTPS source URL.")
    table["evidence_url"] = table["evidence_url"].where(table["evidence_url"].ne(""), table["source_url"])
    if not table["evidence_url"].str.match(r"^https://[^\s/]+\.[^\s]+$").all():
        raise ValueError("Evidence URLs must be valid HTTPS URLs.")
    for _, row in table.iterrows():
        low = pd.to_numeric(row["value_min"], errors="coerce")
        high = pd.to_numeric(row["value_max"], errors="coerce")
        if pd.notna(low) and not np.isfinite(low):
            raise ValueError("Numeric observations must be finite.")
        if row["value_max"]:
            if pd.isna(low) or pd.isna(high) or not np.isfinite(high) or high < low:
                raise ValueError("Numeric ranges need finite ordered value_min / value_max.")
        if row["value_min"].lower() in {"nan", "inf", "-inf", "infinity", "-infinity"}:
            raise ValueError("Observations must not contain NaN or infinite values.")
    table["evidence_status"] = "User supplied; source context provided, not independently verified"
    table["dataset"], table["quality"] = "User observations", "User supplied"
    table["well"] = table.get("well", pd.Series("", index=table.index)).astype(str).str.strip()
    return table[COMBINED_COLUMNS].reset_index(drop=True)


def combined_parameters(field, overview, facts, *, curated=None, user=None,
                        wells=None, tops=None, geometry=None, reservoir_text="", pt_upload=None):
    """Keep distinct observations and sources; never turn well proxies/estimates into reservoir measurements."""
    field = str(field).strip().upper()
    identity = overview.loc[overview["fldName"].astype(str).str.strip().str.upper().eq(field)]
    if identity.empty:
        raise ValueError("Field is not in the SODIR field list.")
    identifier = pd.to_numeric(identity.iloc[-1].get("fldNpdidField"), errors="coerce")
    url = f"https://factpages.sodir.no/en/field/pageview/all/{int(identifier)}" if pd.notna(identifier) and identifier > 0 else ""
    rows = []

    def add(parameter, low, high="", unit="", reservoir="", conditions="", dataset="SODIR description",
            quality="Source-backed", source_url=url, locator="Reservoir description; rule-based extraction",
            well="", status="Official source; extracted, not independently measured"):
        if low is None or pd.isna(low) or low == "" or (quality == "Source-backed" and not source_url):
            return
        rows.append(dict(field=field, parameter=parameter, value_min=low,
                         value_max="" if high is None or pd.isna(high) else high, unit=unit,
                         reservoir=reservoir, conditions=conditions, evidence_status=status,
                         source_title=dataset, source_url=source_url, evidence_url=source_url,
                         source_locator=locator, reviewed_date="", dataset=dataset, quality=quality, well=well))

    fact = facts.loc[field] if field in facts.index else pd.Series(dtype=object)
    interval = "; ".join(fact.get("formations", []) + fact.get("groups", []))
    scope = "Field-description scope; check source for interval, datum and original/current conditions."
    for parameter, low, high, unit in (
        ("Reservoir depth", "depth_min_m", "depth_max_m", "m"),
        ("Water depth", "water_depth_min_m", "water_depth_max_m", "m"),
        ("Reservoir thickness (text)", "reservoir_thickness_min_m", "reservoir_thickness_max_m", "m"),
        ("Reservoir footprint (text)", "reservoir_footprint_min_km2", "reservoir_footprint_max_km2", "km2"),
        ("Pressure (text)", "pressure_bar_text", "pressure_bar_text", "bar"),
        ("Temperature (text)", "temperature_c_text", "temperature_c_text", "degC"),
    ):
        add(parameter, fact.get(low), fact.get(high), unit, interval, scope)
    for parameter, key in (("Producing formations", "formations"), ("Reservoir groups", "groups"),
                           ("Lithology", "lithology"), ("Reservoir quality (text)", "reservoir_quality"),
                           ("Drainage strategy", "drainage_strategy"), ("HPHT statement", "hpht_status")):
        value = fact.get(key)
        if isinstance(value, list):
            value = "; ".join(value)
        if value not in (None, "", "Not stated", "Unknown"):
            add(parameter, value, reservoir=interval, conditions=scope)
    hc_type = identity.iloc[-1].get("fldHcType")
    add("Hydrocarbon type", hc_type, conditions="SODIR field classification; not a fluid composition/PVT measurement.",
        dataset="SODIR field table", locator="fldHcType")
    # Require explicit parameter, numerical value and unit in the same short clause.
    numeric = r"(\d+(?:\.\d+)?)\s*(?:[-–]\s*(\d+(?:\.\d+)?))?"
    for parameter, name, unit_pattern, unit in (
        ("Porosity", r"porosity", r"(?:%|percent|per cent)", "%"),
        ("Permeability", r"permeability", r"(?:mD\b|millidarc(?:y|ies)\b)", "mD"),
        ("Fluid viscosity", r"viscosity", r"(?:cP\b|centipoise\b)", "cP"),
        ("Fluid density", r"density", r"kg\s*/\s*m(?:3|³)", "kg/m3"),
    ):
        pattern = rf"\b{name}\b[^.\d;]{{0,50}}{numeric}\s*{unit_pattern}"
        for match in re.finditer(pattern, reservoir_text, re.I):
            low, high = float(match.group(1)), float(match.group(2) or match.group(1))
            if high < low or (parameter == "Porosity" and high > 100):
                continue
            add(parameter, low, high, unit, interval, scope + " Text clause: " + match.group(0),
                locator="Reservoir description; explicit numerical clause: " + match.group(0))

    literature = field_parameters(field)
    if not literature.empty:
        literature = literature.assign(dataset="Registered literature",
            quality=literature["evidence_status"].map(
                lambda value: "Provisional / unverified" if any(word in value.lower() for word in ("provisional", "unverified", "reference only")) else "Source-backed"),
            well="")
        rows.extend(literature.to_dict("records"))
    curated = load_curated() if curated is None else curated
    curated = curated.assign(dataset_name="Existing P/T table", is_user=False)
    if pt_upload is not None and not pt_upload.empty:
        curated = pd.concat([curated, pt_upload.assign(dataset_name="User P/T upload", is_user=True)], ignore_index=True)
    for observation in curated.loc[curated["field"].eq(field)].to_dict("records"):
        links = re.findall(r"https://[^\s;]+", str(observation.get("source", "")))
        confidence = str(observation.get("confidence", "")).lower()
        quality = "Provisional / unverified" if confidence in ("unverified", "indexed excerpt", "estimate") or not links else "Source-backed"
        if observation["is_user"]:
            quality = "User supplied"
        for parameter, key, unit in (("Pressure (P/T table)", "pressure_bar", "bar"), ("Temperature (P/T table)", "temperature_c", "degC")):
            add(parameter, observation.get(key), unit=unit, reservoir=observation.get("formation") or "",
                conditions=f"P/T table observation; datum depth {observation.get('datum_depth_m')} m; regime {observation.get('regime')}; verify datum and date.",
                dataset=observation["dataset_name"], quality=quality, source_url=links[0] if links else "",
                locator=str(observation.get("source")), status=f"{confidence}; source: {observation.get('source')}")
    pressure, temperature = estimate_from_depth(fact.get("depth_mid_m"), fact.get("water_depth_min_m"))
    for parameter, value, unit in (("Pressure estimate", None if bool(fact.get("hpht", False)) else pressure, "bar"),
                                    ("Temperature estimate", temperature, "degC")):
        add(parameter, value, unit=unit, conditions="Depth-based hydrostatic/geothermal screening estimate, NOT measured. No pressure estimate for stated HPHT.",
            dataset="Depth-based model", quality="Estimate", locator="utils.pt.estimate_from_depth",
            status="Estimate, not a sourced reservoir measurement")
    if geometry is not None:
        add("Field-outline footprint proxy", geometry.get("outline_area_km2"), unit="km2",
            conditions="WGS84 ellipsoidal net field-polygon area; not net reservoir or drainage area.",
            dataset="SODIR field geometry", source_url="https://factmaps.sodir.no/api/rest/services/DataService/Data/MapServer/7100",
            locator="Field polygon geometry; computed geodesic area")
    if wells is not None and not wells.empty and tops is not None and not tops.empty:
        matched = wells.loc[wells["wlbField"].eq(field), "wlbWellboreName"].dropna()
        selected = tops.loc[tops["wlbName"].isin(matched)]
        for record in selected.to_dict("records"):
            top = pd.to_numeric(record.get("lsuTopDepth"), errors="coerce")
            bottom = pd.to_numeric(record.get("lsuBottomDepth"), errors="coerce")
            if pd.notna(top) and pd.notna(bottom) and np.isfinite([top, bottom]).all() and bottom > top >= 0:
                add("Formation interval (MD), not net pay", top, bottom, "m MD RKB", record.get("lsuName", ""),
                    "Well-specific lithostratigraphic interval, NOT producing thickness or true vertical thickness.",
                    dataset="SODIR formation tops",
                    source_url=("https://factpages.sodir.no/public?/Factpages/external/tableview/wellbore_formation_top"
                                "&rs:Command=Render&rc:Toolbar=false&rc:Parameters=f&IpAddress=not_used"
                                "&CultureCode=en&rs:Format=CSV&Top100=false"),
                    locator="wellbore_formation_top: lsuTopDepth / lsuBottomDepth", well=record["wlbName"])
    if user is not None and not user.empty:
        rows.extend(user.loc[user["field"].eq(field), COMBINED_COLUMNS].to_dict("records"))
    return pd.DataFrame(rows, columns=COMBINED_COLUMNS).fillna("").drop_duplicates().reset_index(drop=True)


def field_parameters(field, path=PATH):
    table = pd.read_csv(path, keep_default_na=False)
    if not set(COLUMNS).issubset(table.columns):
        raise ValueError("Reservoir observations are missing required provenance columns.")
    if not table["source_url"].str.startswith("https://").all() or not table["evidence_url"].str.startswith("https://").all():
        raise ValueError("Every reservoir observation requires an HTTPS source URL.")
    if table[["parameter", "conditions", "evidence_status", "source_title", "source_locator", "reviewed_date"]].eq("").any().any():
        raise ValueError("Reservoir observations require parameter, conditions and complete source context.")
    return table.loc[table["field"].str.upper().eq(field.upper()), COLUMNS].reset_index(drop=True)
