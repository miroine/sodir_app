from html import escape
from urllib.parse import urlencode

import pandas as pd
import plotly.graph_objects as go

from utils.data import (
    daily_production,
    latest_row,
    load_dataset,
    number,
    prepare_monthly,
    select_field,
)


def fig_plot_oil(df_selection, rates=None):
    data = prepare_monthly(df_selection)
    rates = daily_production(data) if rates is None else rates
    fig = go.Figure()
    for label, color in (("Oil", "#0f9d82"), ("NGL", "#e6a23c")):
        fig.add_scatter(
            x=rates.index, y=rates[f"{label} [Sm³/d]"],
            name=label, mode="lines", stackgroup="liquids", line_color=color,
        )
    total = data["prfPrdProducedWaterInFieldMillSm3"] + data["prfPrdOilNetMillSm3"]
    fig.add_scatter(
        x=data.index,
        y=data["prfPrdProducedWaterInFieldMillSm3"].div(total.where(total > 0)),
        name="Water cut", mode="lines", yaxis="y2", line_color="#5b8def",
    )
    fig.update_layout(
        title="Liquid production", yaxis_title="Sm³/day",
        yaxis2=dict(
            title="Water cut", side="right", overlaying="y",
            range=[0, 1], tickformat=".0%",
        ),
        hovermode="x unified", legend_orientation="h",
    )
    return fig


def fig_plot_gas(df_selection, rates=None):
    rates = daily_production(df_selection) if rates is None else rates
    fig = go.Figure()
    fig.add_scatter(
        x=rates.index, y=rates["Gas [million Sm³/d]"],
        name="Gas", mode="lines", fill="tozeroy", line_color="#5b8def",
    )
    fig.add_scatter(
        x=rates.index, y=rates["Condensate [Sm³/d]"],
        name="Condensate", mode="lines", yaxis="y2", line_color="#d575ad",
    )
    fig.update_layout(
        title="Gas & condensate production", yaxis_title="Gas · million Sm³/day",
        yaxis2=dict(title="Condensate · Sm³/day", side="right", overlaying="y"),
        hovermode="x unified", legend_orientation="h",
    )
    return fig


def update_tail_production(df_selection, rates=None):
    rates = (daily_production(df_selection) if rates is None else rates).tail(12).copy()
    rates.index = rates.index.strftime("%m.%Y")
    rates.index.name = "Month"
    return rates


def get_field_info(selected_field, overview=None, inplace=None, production=None):
    overview = load_dataset("overview") if overview is None else overview
    inplace = load_dataset("inplace") if inplace is None else inplace
    production = load_dataset("monthly") if production is None else production
    info = latest_row(select_field(overview, selected_field))
    volumes = latest_row(select_field(inplace, selected_field))
    produced = select_field(production, selected_field, "prfInformationCarrier")
    lines = []
    for label, column in (
        ("Status", "fldCurrentActivitySatus"), ("Area", "fldMainArea"),
        ("Discovery well", "wlbName"), ("Discovery date", "wlbCompletionDate"),
        ("Operator", "cmpLongName"),
    ):
        value = info.get(column)
        lines.append(f"**{label}:** {value if pd.notna(value) else 'Not available'}")
    oil = number(volumes, "fldInplaceOil")
    gas_parts = [number(volumes, col) for col in ("fldInplaceFreeGas", "fldInplaceAssGas")]
    gas = sum(gas_parts) if all(value is not None for value in gas_parts) else None
    for label, volume, column, unit in (
        ("Oil", oil, "prfPrdOilNetMillSm3", "million Sm³"),
        ("Gas", gas, "prfPrdGasNetBillSm3", "billion Sm³"),
    ):
        if volume is not None:
            lines.append(f"**{label} in place:** {volume:,.1f} {unit}")
        cumulative = pd.to_numeric(produced.get(column, pd.Series(dtype=float)), errors="coerce").sum(min_count=1)
        if volume is not None and volume > 0 and pd.notna(cumulative):
            lines.append(f"**{label} recovery factor:** {cumulative / volume:.1%}")
    return "  \n".join(lines)


def field_map_url(selected_field, overview=None):
    overview = load_dataset("overview") if overview is None else overview
    info = latest_row(select_field(overview, selected_field))
    field_id = number(info, "fldNpdidField")
    if field_id is None or field_id <= 0 or not field_id.is_integer():
        return None
    query = urlencode(dict(entity="field", npdid=int(field_id), shellMode="handheld"))
    return f"https://factmaps.sodir.no/factmaplink/?{query}"


def field_map(selected_field, overview=None):
    """Compatibility HTML helper; the dashboard uses Streamlit's iframe component."""
    url = field_map_url(selected_field, overview)
    if url is None:
        return ""
    return (
        f'<iframe title="SODIR field map" width="100%" height="560" '
        f'src="{escape(url, quote=True)}" style="border:0" allowfullscreen></iframe>'
    )


def reserve_figure(selected_field, product, reserves=None, inplace=None, production=None):
    reserves = load_dataset("reserves") if reserves is None else reserves
    inplace = load_dataset("inplace") if inplace is None else inplace
    production = load_dataset("monthly") if production is None else production
    reserve = latest_row(select_field(reserves, selected_field))
    volume = latest_row(select_field(inplace, selected_field))
    remaining = number(reserve, f"fldRemaining{product}")
    recoverable = number(reserve, f"fldRecoverable{product}")
    if remaining is None or recoverable is None:
        return None
    columns = ["fldInplaceOil"] if product == "Oil" else ["fldInplaceFreeGas", "fldInplaceAssGas"]
    parts = [number(volume, col) for col in columns]
    if any(value is None for value in parts):
        return None
    in_place = sum(parts)
    produced_data = select_field(production, selected_field, "prfInformationCarrier")
    column = "prfPrdOilNetMillSm3" if product == "Oil" else "prfPrdGasNetBillSm3"
    produced = pd.to_numeric(
        produced_data.get(column, pd.Series(dtype=float)), errors="coerce"
    ).sum(min_count=1)
    if pd.isna(produced):
        return None
    unit = "million Sm³" if product == "Oil" else "billion Sm³"
    upper = max(in_place, produced + remaining, recoverable)
    if upper <= 0:
        upper = 1
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=produced,
        title=dict(text=f"{product} produced · {unit}"),
        gauge=dict(
            axis=dict(range=[0, upper]), bar=dict(color="#0f9d82"),
            steps=[
                dict(range=[0, produced], color="#0f9d82"),
                dict(range=[produced, produced + remaining], color="#8ad8c7"),
            ],
            threshold=dict(line=dict(color="#e6a23c", width=3), value=recoverable),
        ),
    ))
    fig.update_layout(height=300, margin=dict(l=35, r=35, t=65, b=20))
    return fig


def callback_plot_reserve(selected_field, **datasets):
    return reserve_figure(selected_field, "Oil", **datasets)


def callback_plot_gas(selected_field, **datasets):
    return reserve_figure(selected_field, "Gas", **datasets)


def callback_reserves(selected_field):
    row = latest_row(select_field(load_dataset("reserves"), selected_field))
    # Gas billion Sm³ converts to million Sm³ oil equivalent at a factor of 1.
    values = [number(row, f"fldRemaining{product}") for product in ("Oil", "Gas", "NGL", "Condensate")]
    if any(value is None for value in values):
        return None
    values[2] *= 1.9
    return go.Figure(go.Pie(
        labels=["Oil", "Gas", "NGL", "Condensate"], values=values, hole=0.4,
        title=dict(text="Remaining reserves · million Sm³ oil equivalent"),
    ))


def callback_investments(selected_field, investments=None):
    investments = load_dataset("investments") if investments is None else investments
    data = select_field(investments, selected_field, "prfInformationCarrier")
    if data.empty or not {"prfYear", "prfInvestmentsMillNOK"}.issubset(data.columns):
        return None
    data["prfYear"] = pd.to_numeric(data["prfYear"], errors="coerce")
    data["prfInvestmentsMillNOK"] = pd.to_numeric(data["prfInvestmentsMillNOK"], errors="coerce")
    data = data.dropna(subset=["prfYear", "prfInvestmentsMillNOK"]).sort_values("prfYear")
    if data.empty:
        return None
    fig = go.Figure(go.Bar(
        x=data["prfYear"], y=data["prfInvestmentsMillNOK"], marker_color="#5b8def",
    ))
    fig.update_layout(title="Annual investments", yaxis_title="Million NOK", xaxis_title="Year")
    return fig
