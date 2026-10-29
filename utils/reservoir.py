"""Source-linked reservoir observations; no estimated values for missing literature facts."""
from pathlib import Path

import pandas as pd

PATH = Path(__file__).resolve().parents[1] / "data" / "reservoir_parameters.csv"
COLUMNS = [
    "field", "parameter", "value_min", "value_max", "unit", "reservoir",
    "conditions", "evidence_status", "source_title", "source_url", "evidence_url", "source_locator", "reviewed_date",
]


def field_parameters(field, path=PATH):
    table = pd.read_csv(path, keep_default_na=False)
    if not set(COLUMNS).issubset(table.columns):
        raise ValueError("Reservoir observations are missing required provenance columns.")
    if not table["source_url"].str.startswith("https://").all() or not table["evidence_url"].str.startswith("https://").all():
        raise ValueError("Every reservoir observation requires an HTTPS source URL.")
    if table[["parameter", "conditions", "evidence_status", "source_title", "source_locator", "reviewed_date"]].eq("").any().any():
        raise ValueError("Reservoir observations require parameter, conditions and complete source context.")
    return table.loc[table["field"].str.upper().eq(field.upper()), COLUMNS].reset_index(drop=True)
