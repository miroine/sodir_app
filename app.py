from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

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
from utils.data import DataUnavailable, load_dataset, select_field


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
st.sidebar.caption("Switch light / dark mode in Streamlit Settings → Theme.")
if st.sidebar.button("Refresh SODIR data", use_container_width=True):
    load_dataset.clear()
st.sidebar.caption("Data cached for one hour. Only the active section is loaded.")


def optional_dataset(name):
    try:
        with st.spinner(f"Loading SODIR {name}…"):
            return load_dataset(name)
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
    st.plotly_chart(fig, use_container_width=True, theme="streamlit")


try:
    with st.spinner("Loading the field catalogue…"):
        overview = load_dataset("overview")
except DataUnavailable as exc:
    st.error(str(exc))
    st.info("Try Refresh SODIR data in the sidebar. FactMaps can still be opened directly.")
    st.link_button("Open SODIR FactMaps", "https://factmaps.sodir.no/")
    st.stop()

fields = sorted(overview["fldName"].dropna().unique().tolist())
if not fields:
    st.warning("SODIR returned an empty field catalogue. Please try refreshing.")
    st.stop()
selected_field = st.sidebar.selectbox(
    "Field", fields, index=fields.index("OSEBERG") if "OSEBERG" in fields else 0,
)
section = st.sidebar.radio("Explore", ["Overview", "Production", "Reserves", "Investments"])
st.sidebar.divider()
st.sidebar.caption("Source: Norwegian Offshore Directorate (SODIR)")
st.title(selected_field)
st.caption("FIELD INTELLIGENCE  /  NORWEGIAN CONTINENTAL SHELF")

if section in ("Overview", "Production", "Reserves"):
    monthly = optional_dataset("monthly")
    production = select_field(monthly, selected_field, "prfInformationCarrier")

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
            components.iframe(url, height=560, scrolling=True)
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
                    descriptions["fldDescriptionHeading"].str.contains(
                        heading, case=False, na=False, regex=False
                    ), "fldDescriptionText"
                ].dropna()
                with st.expander(heading):
                    st.markdown("\n\n".join(entries.astype(str)) if not entries.empty else "Not available.")

elif section == "Production":
    if production.empty:
        st.info("No monthly production has been reported for this field.")
    else:
        st.caption("Daily averages use the actual number of days in each reporting month.")
        show_chart(fig_plot_oil(production))
        show_chart(fig_plot_gas(production))
        st.subheader("Latest 12 reported months")
        tail = update_tail_production(production)
        columns = st.multiselect("Displayed products", tail.columns, default=tail.columns.tolist())
        st.dataframe(tail[columns], use_container_width=True)
        st.download_button(
            "Download monthly production CSV",
            production.to_csv().encode("utf-8"), file_name=f"{selected_field}_production.csv",
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
