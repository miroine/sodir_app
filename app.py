from pathlib import Path
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from utils.callbaks_figure import (
    callback_investments,
    callback_plot_gas,
    callback_plot_reserve,
    field_map_url,
    fig_plot_gas,
    fig_plot_oil,
    get_field_info,
    update_tail_production,
)
from utils.data import DataUnavailable, daily_production, latest_row, load_dataset, number, select_field
from utils.maps import load_field_geometry, load_map_layers, map_document


ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="SODIR · Field Explorer", page_icon="🌊", layout="wide")

st.sidebar.title("🌊 Field Explorer")
st.sidebar.caption("Norwegian continental shelf · SODIR")
palette = st.sidebar.selectbox("Accent palette", ["Ocean", "Forest", "Sunset"])
accents = {"Ocean": "#168aad", "Forest": "#0f9d82", "Sunset": "#cb6b28"}
st.markdown(
    f"<style>:root {{ --explorer-accent: {accents[palette]}; }}"
    f"{(ROOT / 'style.css').read_text()}</style>",
    unsafe_allow_html=True,
)
if st.sidebar.button("Refresh SODIR data", width="stretch"):
    load_dataset.clear()
    load_map_layers.clear()
    load_field_geometry.clear()
    st.session_state.pop("data_failures", None)
st.sidebar.caption("Data cached for one hour. Only the active section is loaded.")


def available_dataset(name):
    snapshots = st.session_state.setdefault("data_snapshots", {})
    failures = st.session_state.setdefault("data_failures", {})
    now = datetime.now(timezone.utc)
    try:
        if name in failures and now < failures[name][0]:
            raise DataUnavailable(failures[name][1])
        with st.spinner(f"Loading SODIR {name}…"):
            result = load_dataset(name)
        snapshots[name] = (result, result.attrs.get("fetched_at", now))
        failures.pop(name, None)
        return result
    except DataUnavailable as exc:
        if name not in failures or now >= failures[name][0]:
            failures[name] = (now + timedelta(seconds=60), str(exc))
        if name not in snapshots:
            raise
        result, fetched_at = snapshots[name]
        st.warning(
            f"SODIR {name} is unavailable. Showing previously loaded data from "
            f"{fetched_at:%Y-%m-%d %H:%M UTC}; it may be out of date."
        )
        return result


def optional_dataset(name):
    try:
        return available_dataset(name)
    except DataUnavailable as exc:
        st.warning(str(exc))
        return pd.DataFrame()


def show_chart(fig):
    if fig is None:
        st.info("No data available for this field.")
        return
    fig.update_layout(
        margin=dict(l=40, r=40, t=65, b=40),
        legend_orientation="h",
        font=dict(family="Arial, sans-serif"),
    )
    if appearance != "System":
        fig.update_layout(
            template="plotly_dark" if appearance == "Dark" else "plotly_white",
            paper_bgcolor=theme_colors["surface"], plot_bgcolor=theme_colors["surface"],
            font_color=theme_colors["text"],
        )
    st.plotly_chart(fig, width="stretch", theme="streamlit" if appearance == "System" else None)


try:
    overview = available_dataset("overview")
except DataUnavailable as exc:
    st.error(str(exc))
    st.info("Try Refresh SODIR data in the sidebar, or retry after a minute. FactMaps can still be opened directly.")
    st.link_button("Open SODIR FactMaps", "https://factmaps.sodir.no/")
    st.stop()

fields = sorted(overview["fldName"].dropna().unique().tolist())
if not fields:
    st.warning("SODIR returned an empty field catalogue. Please try refreshing.")
    st.stop()
selected_field = st.sidebar.selectbox(
    "Field", fields, index=fields.index("OSEBERG") if "OSEBERG" in fields else 0, key="field",
)
appearance = st.sidebar.selectbox("Appearance", ["System", "Light", "Dark"], key="appearance")
theme_colors = (
    {"background": "#0b1524", "surface": "#142238", "text": "#ecf2fa"}
    if appearance == "Dark"
    else {"background": "#f4f7fb", "surface": "#ffffff", "text": "#172b43"}
)
if appearance != "System":
    st.markdown(
        "<style>.stApp {"
        f"--background-color: {theme_colors['background']};"
        f"--secondary-background-color: {theme_colors['surface']};"
        f"--text-color: {theme_colors['text']};"
        f"background-color: {theme_colors['background']}; color: {theme_colors['text']};"
        "}"
        "[data-testid='stSidebar'], [data-testid='stHeader'] {"
        "background-color: var(--secondary-background-color); color: var(--text-color);"
        "}"
        ".stApp h1, .stApp h2, .stApp h3, .stApp p, .stApp label,"
        ".stApp [data-testid='stMetricValue'] {color: var(--text-color);}"
        ".stApp [data-baseweb='select'] > div, .stApp button,"
        ".stApp input, .stApp [data-baseweb='input'] {"
        "background-color: var(--secondary-background-color); color: var(--text-color);}"
        ".stApp [data-testid='stAlert'] {"
        "background-color: var(--secondary-background-color); color: var(--text-color);}"
        "</style>",
        unsafe_allow_html=True,
    )
section = st.sidebar.radio(
    "Explore", ["Overview", "Map", "Production", "Reserves", "Investments"], key="section",
)
st.sidebar.divider()
st.sidebar.caption("Source: Norwegian Offshore Directorate (SODIR)")
st.title(selected_field)
st.caption("FIELD INTELLIGENCE  /  NORWEGIAN CONTINENTAL SHELF")

if section in ("Overview", "Production", "Reserves"):
    monthly = optional_dataset("monthly")
    production = select_field(monthly, selected_field, "prfInformationCarrier")
    if not production.empty and production.filter(regex="^prfPrd").isna().any().any():
        st.warning("Some production values are missing. Totals and charts use only reported values.")

if section == "Overview":
    st.subheader("Cumulative production")
    metrics = [
        ("Oil", "prfPrdOilNetMillSm3", "million Sm³"),
        ("Gas", "prfPrdGasNetBillSm3", "billion Sm³"),
        ("NGL", "prfPrdNGLNetMillSm3", "million Sm³"),
        ("Condensate", "prfPrdCondensateNetMillSm3", "million Sm³"),
        ("Water", "prfPrdProducedWaterInFieldMillSm3", "million Sm³"),
    ]
    for container, (label, column, unit) in zip(st.columns(5), metrics):
        total = pd.to_numeric(
            production.get(column, pd.Series(dtype=float)), errors="coerce"
        ).sum(min_count=1)
        container.metric(label, f"{total:,.1f}" if pd.notna(total) else "—")
        container.caption(unit)
    if not production.empty:
        st.caption(f"Production data through {production.index.max():%B %Y}.")

    details, map_panel = st.columns([1, 2], gap="large")
    with details:
        st.subheader("Field overview")
        inplace = optional_dataset("inplace")
        st.markdown(get_field_info(selected_field, overview, inplace, monthly))
    with map_panel:
        st.subheader("SODIR FactMaps")
        url = field_map_url(selected_field, overview)
        if url:
            st.iframe(url, height=560, alt=f"SODIR FactMaps · {selected_field}")
            st.link_button("Open selected field in FactMaps ↗", url)
            st.caption(
                "Official SODIR viewer, linked using the selected field's SODIR ID. "
                "Map layers are controlled within the SODIR viewer. If the embedded "
                "viewer is unavailable, open FactMaps above."
            )
        else:
            st.info("No valid SODIR map identifier is available for this field.")
    if st.checkbox("Show field development and reservoir descriptions"):
        descriptions = select_field(optional_dataset("description"), selected_field)
        if not {"fldDescriptionHeading", "fldDescriptionText"}.issubset(descriptions.columns):
            st.info("No field descriptions available.")
        else:
            for heading in ("Development", "Status", "Reservoir", "Recovery", "Transport"):
                entries = descriptions.loc[
                    descriptions["fldDescriptionHeading"].astype("string").str.contains(
                        heading, case=False, na=False, regex=False
                    ), "fldDescriptionText"
                ].dropna()
                with st.expander(heading):
                    st.markdown("\n\n".join(entries.astype(str)) if not entries.empty else "Not available.")

elif section == "Map":
    st.subheader("SODIR map layers")
    url = field_map_url(selected_field, overview)
    mode = st.radio("Map mode", ["Layer controls", "Official viewer"], horizontal=True)
    rendered = False
    if url and mode == "Layer controls":
        try:
            with st.spinner("Loading SODIR layer catalogue and selected-field boundary…"):
                catalogue = load_map_layers()
                field_id = int(number(latest_row(select_field(overview, selected_field)), "fldNpdidField"))
                geometry = load_field_geometry(field_id)
            defaults = [key for key, title in catalogue.items() if "field" in title.lower()][:3]
            previous = st.session_state.get("map_layers")
            if previous is not None:
                st.session_state["map_layers"] = [key for key in previous if key in catalogue]
            selected_layers = st.multiselect(
                "SODIR overlays", list(catalogue),
                default=(defaults or list(catalogue)[:1]) if previous is None else None,
                format_func=lambda key: f"{catalogue[key]} ({key})", key="map_layers",
            )
            st.iframe(
                map_document(
                    selected_field, geometry, {key: catalogue[key] for key in selected_layers},
                    dark=appearance == "Dark",
                ),
                height=565, alt=f"SODIR layers and boundary · {selected_field}",
            )
            st.caption(
                "Layers come from SODIR's live WMS catalogue. Amber boundaries / points "
                "come from its field geometry service. Only selected overlays request tiles."
            )
            rendered = True
        except DataUnavailable as exc:
            st.warning(f"{exc} Showing the official viewer instead.")
    if url:
        if not rendered:
            st.iframe(url, height=560, alt=f"SODIR FactMaps · {selected_field}")
        st.link_button("Open selected field in FactMaps ↗", url)
    else:
        st.info("No valid SODIR map identifier is available for this field.")

elif section == "Production":
    if production.empty:
        st.info("No monthly production has been reported for this field.")
    else:
        months = sorted(production.index.unique())
        period_key = f"period_{selected_field}"
        previous = st.session_state.get(period_key)
        if previous is not None and any(month not in months for month in previous):
            st.session_state.pop(period_key)
        start, end = st.select_slider(
            "Reporting period", options=months, value=(months[0], months[-1]),
            format_func=lambda month: month.strftime("%b %Y"), key=period_key,
        )
        filtered = production.loc[start:end]
        rates = daily_production(filtered)
        st.caption("Daily averages use the actual number of days in each reporting month.")
        show_chart(fig_plot_oil(filtered, rates=rates))
        show_chart(fig_plot_gas(filtered, rates=rates))
        st.subheader("Latest 12 months in selected period")
        tail = update_tail_production(filtered, rates=rates)
        columns = st.multiselect("Displayed products", tail.columns, default=tail.columns.tolist())
        st.dataframe(tail[columns], width="stretch")
        st.download_button(
            "Download monthly production CSV",
            filtered.to_csv().encode("utf-8"), file_name=f"{selected_field}_production.csv",
            mime="text/csv",
        )

elif section == "Reserves":
    reserves = optional_dataset("reserves")
    inplace = optional_dataset("inplace")
    st.subheader("Produced volumes & remaining reserves")
    st.caption(
        "Gauge number: cumulative production. Pale band: remaining reserves. "
        "Amber marker: recoverable volume. Scale: in-place volume or the largest reported value."
    )
    for container, callback in zip(st.columns(2), (callback_plot_reserve, callback_plot_gas)):
        with container:
            show_chart(callback(selected_field, reserves=reserves, inplace=inplace, production=monthly))

elif section == "Investments":
    show_chart(callback_investments(selected_field, optional_dataset("investments")))
