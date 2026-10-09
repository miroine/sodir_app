from io import BytesIO
from datetime import datetime, timezone
from math import isfinite
from urllib.request import urlopen

import pandas as pd
import streamlit as st


DATASETS = {
    "overview": ("field", "fldName"),
    "monthly": ("field_production_monthly", "prfInformationCarrier"),
    "inplace": ("field_in_place_volumes", "fldName"),
    "reserves": ("field_reserves", "fldName"),
    "description": ("field_description", "fldName"),
    "investments": ("field_investment_yearly", "prfInformationCarrier"),
}
PRODUCTION_COLUMNS = {
    "prfPrdOilNetMillSm3": "Oil [Sm³/d]",
    "prfPrdGasNetBillSm3": "Gas [million Sm³/d]",
    "prfPrdNGLNetMillSm3": "NGL [Sm³/d]",
    "prfPrdCondensateNetMillSm3": "Condensate [Sm³/d]",
    "prfPrdOeNetMillSm3": "Oil equivalent [Sm³/d]",
    "prfPrdProducedWaterInFieldMillSm3": "Water [Sm³/d]",
}


class DataUnavailable(RuntimeError):
    pass


def prepare_monthly(data):
    data = data.copy()
    if {"prfYear", "prfMonth"}.issubset(data.columns):
        data.index = pd.to_datetime(
            dict(
                year=pd.to_numeric(data["prfYear"], errors="coerce"),
                month=pd.to_numeric(data["prfMonth"], errors="coerce"),
                day=1,
            ),
            errors="coerce",
        )
    elif not isinstance(data.index, pd.DatetimeIndex):
        raise ValueError("Production dates are missing.")
    data = data.loc[data.index.notna()].sort_index()
    data.index.name = "Date"
    for column in PRODUCTION_COLUMNS:
        if column not in data:
            data[column] = float("nan")
        data[column] = pd.to_numeric(data[column], errors="coerce").replace(
            [float("inf"), float("-inf")], float("nan")
        )
    return data


@st.cache_data(ttl=3600, max_entries=len(DATASETS), show_spinner=False)
def load_dataset(name):
    """Cache each full SODIR table across fields; failed requests are not cached."""
    table, field_column = DATASETS[name]
    url = (
        f"https://factpages.sodir.no/public?/Factpages/external/tableview/{table}"
        "&rs:Command=Render&rc:Toolbar=false&rc:Parameters=f&IpAddress=not_used"
        "&CultureCode=en&rs:Format=CSV&Top100=false"
    )
    try:
        with urlopen(url, timeout=20) as response:
            data = pd.read_csv(BytesIO(response.read()))
        if field_column not in data.columns:
            raise ValueError("Unexpected SODIR table format.")
        if name == "monthly":
            data = prepare_monthly(data)
        data.attrs["fetched_at"] = datetime.now(timezone.utc)
        return data
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        raise DataUnavailable(f"SODIR {name} data is temporarily unavailable.") from exc


def select_field(data, selected_field, column="fldName"):
    if column not in data:
        return data.iloc[:0].copy()
    return data.loc[data[column] == selected_field].copy()


def daily_production(data):
    data = prepare_monthly(data)
    days = pd.Series(data.index.days_in_month, index=data.index)
    rates = data[list(PRODUCTION_COLUMNS)].div(days, axis=0) * 1e6
    # Gas is reported in billion Sm³/month, so this yields million Sm³/day.
    rates["prfPrdGasNetBillSm3"] /= 1e3
    return rates.rename(columns=PRODUCTION_COLUMNS)


def latest_row(data):
    for column in ("fldDateOffResEstDisplay", "fldDateOffResEst"):
        if column in data:
            text = data[column].astype("string")
            iso = text.str.match(r"^\d{4}-\d{2}-\d{2}", na=False)
            dates = pd.to_datetime(text.where(iso), errors="coerce", format="ISO8601")
            dates = dates.fillna(pd.to_datetime(
                text.where(~iso), errors="coerce", dayfirst=True, format="mixed",
            ))
            data = data.assign(_estimate_date=dates).sort_values(
                "_estimate_date", na_position="first"
            )
            break
    return data.iloc[-1] if not data.empty else pd.Series(dtype=object)


def number(row, column):
    value = pd.to_numeric(row.get(column), errors="coerce")
    return float(value) if pd.notna(value) and isfinite(float(value)) else None
