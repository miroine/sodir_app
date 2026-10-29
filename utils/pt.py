"""Reservoir pressure and temperature: curated table, text-stated values and depth-based estimates.

SODIR publishes no pressure/temperature table. The app therefore combines, in order of
preference: (1) a user-supplied CSV, (2) the built-in curated table (public literature,
indicative), (3) explicit numbers in the SODIR description text, (4) a hydrostatic /
geothermal estimate from the extracted reservoir depth. The `source` column always says
which one was used.
"""
from pathlib import Path

import pandas as pd

CURATED_PATH = Path(__file__).resolve().parents[1] / "data" / "reservoir_pt.csv"
PT_COLUMNS = ["field", "formation", "datum_depth_m", "pressure_bar", "temperature_c", "regime", "confidence", "source"]
HYDROSTATIC_BAR_PER_M = 0.101      # ~1.03 g/cm3 formation brine
GEOTHERMAL_C_PER_M = 0.035         # NCS average 30-40 C/km
SEABED_TEMPERATURE_C = 4.0


def load_curated(path=CURATED_PATH):
    try:
        table = pd.read_csv(path)
    except (OSError, pd.errors.ParserError):
        return pd.DataFrame(columns=PT_COLUMNS)
    return normalise_pt(table)


def normalise_pt(table):
    """Accept flexible column names (case/space insensitive) and coerce numeric columns."""
    table = table.copy()
    aliases = {
        "field": ("field", "fldname", "field name", "name"),
        "formation": ("formation", "reservoir", "fm"),
        "datum_depth_m": ("datum_depth_m", "depth", "depth_m", "datum", "datum depth"),
        "pressure_bar": ("pressure_bar", "pressure", "p_bar", "pi", "initial pressure", "pressure (bar)"),
        "temperature_c": ("temperature_c", "temperature", "t_c", "temp", "reservoir temperature", "temperature (c)"),
        "regime": ("regime", "pressure regime", "comment"),
        "confidence": ("confidence", "quality"),
        "source": ("source", "reference"),
    }
    lookup = {str(column).strip().lower(): column for column in table.columns}
    renamed = {}
    for target, names in aliases.items():
        for name in names:
            if name in lookup:
                renamed[lookup[name]] = target
                break
    table = table.rename(columns=renamed)
    for column in PT_COLUMNS:
        if column not in table:
            table[column] = None
    table = table[PT_COLUMNS]
    table["field"] = table["field"].astype("string").str.strip().str.upper()
    for column in ("datum_depth_m", "pressure_bar", "temperature_c"):
        table[column] = pd.to_numeric(table[column], errors="coerce")
    table = table.dropna(subset=["field"])
    table = table.loc[table["pressure_bar"].notna() | table["temperature_c"].notna()]
    return table.reset_index(drop=True)


def estimate_from_depth(depth_m, water_depth_m=None):
    """Hydrostatic pressure and geothermal temperature at a sub-sea depth (metres)."""
    if depth_m is None or pd.isna(depth_m) or depth_m <= 0:
        return None, None
    pressure = HYDROSTATIC_BAR_PER_M * float(depth_m)
    sediment = float(depth_m) - (float(water_depth_m) if water_depth_m is not None and pd.notna(water_depth_m) else 0.0)
    temperature = SEABED_TEMPERATURE_C + GEOTHERMAL_C_PER_M * max(sediment, 0.0)
    return round(pressure), round(temperature)


def pt_for_fields(facts, curated=None, user_table=None):
    """One row per field with pressure, temperature, basis and confidence.

    `facts` is the extraction table (index = field name) with depth_mid_m,
    water_depth_min_m, hpht, pressure_bar_text and temperature_c_text columns.
    """
    curated = load_curated() if curated is None else curated
    rows = []
    sources = []
    if user_table is not None and not user_table.empty:
        sources.append(("User table", user_table))
    sources.append(("Curated table", curated))
    for field in facts.index:
        fact = facts.loc[field]
        record = dict(field=field, formation=None, datum_depth_m=fact.get("depth_mid_m"),
                      pressure_bar=None, temperature_c=None, regime=None, confidence=None, source=None)
        for label, table in sources:
            hit = table.loc[table["field"] == str(field).upper()]
            if not hit.empty:
                hit = hit.iloc[0]
                record.update(
                    formation=hit["formation"], pressure_bar=hit["pressure_bar"],
                    temperature_c=hit["temperature_c"], regime=hit["regime"],
                    confidence=hit["confidence"] if pd.notna(hit["confidence"]) else "stated",
                    source=label if pd.isna(hit["source"]) else f"{label}: {hit['source']}",
                )
                if pd.notna(hit["datum_depth_m"]):
                    record["datum_depth_m"] = hit["datum_depth_m"]
                break
        if record["pressure_bar"] is None and pd.notna(fact.get("pressure_bar_text")):
            record.update(pressure_bar=fact["pressure_bar_text"], confidence="stated", source="SODIR description text")
        if record["temperature_c"] is None and pd.notna(fact.get("temperature_c_text")):
            record.update(temperature_c=fact["temperature_c_text"], confidence="stated",
                          source=record["source"] or "SODIR description text")
        if record["pressure_bar"] is None or record["temperature_c"] is None:
            pressure, temperature = estimate_from_depth(fact.get("depth_mid_m"), fact.get("water_depth_min_m"))
            hpht = bool(fact.get("hpht"))
            if record["pressure_bar"] is None and pressure is not None and not hpht:
                record["pressure_bar"] = pressure
            if record["temperature_c"] is None and temperature is not None:
                record["temperature_c"] = temperature
            if record["source"] is None and (pressure is not None or temperature is not None):
                record["confidence"] = "estimate"
                record["source"] = "Hydrostatic / geothermal estimate from text depth"
                record["regime"] = "HPHT (text) - pressure estimate not applicable" if hpht else "Assumed normally pressured"
        rows.append(record)
    table = pd.DataFrame(rows, columns=PT_COLUMNS)
    return table.set_index("field")
