from datetime import datetime, timedelta, timezone
from html import escape
import math
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils import benchmark as bm
from utils import figures, theme
from utils.callbaks_figure import (
    callback_investments,
    callback_plot_gas,
    callback_plot_reserve,
    field_map_url,
    fig_plot_gas,
    fig_plot_oil,
    update_tail_production,
)
from utils.data import DataUnavailable, daily_production, latest_row, load_dataset, number, select_field
from utils.extract import SECTIONS, facts_table, sections_for_field
from utils.maps import load_field_geometry, load_map_layers, map_document
from utils.pt import PT_COLUMNS, load_curated, normalise_pt, pt_for_fields

ROOT = Path(__file__).resolve().parent
CURRENT_YEAR = datetime.now(timezone.utc).year
SECTION_NAMES = ["Overview", "Production", "Wells & reservoir", "Reserves", "Investments", "Map", "Benchmark", "Data & QA"]

st.set_page_config(page_title="NCS Field Intelligence · SODIR", page_icon="◆", layout="wide")


# ----------------------------------------------------------------------------- data access
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


@st.cache_data(show_spinner=False, max_entries=4)
def compute_facts(descriptions):
    return facts_table(descriptions)


@st.cache_data(show_spinner=False, max_entries=6)
def compute_master(overview, reserves, inplace, yearly, wells, descriptions, user_pt, current_year, start_threshold):
    facts = compute_facts(descriptions)
    pt = pt_for_fields(facts, user_table=user_pt) if not facts.empty else pd.DataFrame()
    master = bm.build_master(overview, reserves, inplace, yearly, wells, facts, pt, current_year, start_threshold)
    return master, facts, pt


def get_master(start_threshold=0.0):
    tables = {name: optional_dataset(name) for name in ("reserves", "inplace", "yearly", "wells", "description")}
    user_pt = st.session_state.get("user_pt")
    return compute_master(
        overview, tables["reserves"], tables["inplace"], tables["yearly"], tables["wells"], tables["description"],
        user_pt, CURRENT_YEAR, start_threshold,
    ) + (tables,)


# ----------------------------------------------------------------------------- presentation helpers
def show_chart(fig, key=None):
    if fig is None:
        st.info("No data available for this field.")
        return
    theme.style(fig, dark=dark)
    st.plotly_chart(fig, width="stretch", theme=None, key=key)


def header(eyebrow, title, lede=None):
    st.markdown(f"<div class='eyebrow'>{escape(eyebrow)}</div>", unsafe_allow_html=True)
    st.title(title)
    if lede:
        st.markdown(f"<p class='lede'>{lede}</p>", unsafe_allow_html=True)


def flags(values, primary=None):
    out = []
    for value in values:
        cls = "flag primary" if value == primary else "flag"
        out.append(f"<span class='{cls}'>{escape(str(value))}</span>")
    return "".join(out) if out else "—"


def fmt(value, pattern="{:,.0f}", suffix=""):
    if value is None or value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        return pattern.format(value) + suffix
    except (ValueError, TypeError):
        return escape(str(value))


def text(value):
    """HTML-escaped text, or an em dash for missing values."""
    if value is None or value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return escape(str(value))


def ceil_ten(value, minimum=10.0):
    """Slider upper bound: next multiple of ten at or above the data maximum."""
    if value is None or pd.isna(value):
        return float(minimum)
    return float(max(minimum, math.ceil(float(value) / 10.0) * 10.0))


def facts_html(rows):
    body = "".join(f"<tr><td>{escape(label)}</td><td>{value}</td></tr>" for label, value in rows)
    return f"<table class='facts'>{body}</table>"


def field_fact_rows(field, master, facts, pt):
    row = master.loc[field] if field in master.index else pd.Series(dtype=object)
    fact = facts.loc[field] if field in facts.index else pd.Series(dtype=object)
    p = pt.loc[field] if field in pt.index else pd.Series(dtype=object)
    depth = "—"
    if pd.notna(fact.get("depth_min_m")):
        depth = f"{fact['depth_min_m']:,.0f}" + (f"–{fact['depth_max_m']:,.0f}" if fact.get("depth_max_m") != fact.get("depth_min_m") else "") + " m"
    water = "—"
    if pd.notna(fact.get("water_depth_min_m")):
        water = f"{fact['water_depth_min_m']:,.0f}" + (f"–{fact['water_depth_max_m']:,.0f}" if fact.get("water_depth_max_m") != fact.get("water_depth_min_m") else "") + " m"
    pt_text = "—"
    if pd.notna(p.get("pressure_bar")) or pd.notna(p.get("temperature_c")):
        pt_text = f"{fmt(p.get('pressure_bar'))} bar · {fmt(p.get('temperature_c'))} °C"
        pt_text += f"<br><small>{text(p.get('confidence'))} · {text(p.get('source'))}</small>"
    identity = [
        ("Status", f"{text(row.get('status'))} · {text(row.get('hc_type'))}"),
        ("Operator", text(row.get("operator"))),
        ("Area", text(row.get("area")) + (f" · {escape(str(fact['sub_area']))}" if isinstance(fact.get("sub_area"), str) else "")),
        ("Timeline", f"Discovered {fmt(fact.get('discovery_year'), '{:.0f}')} · PDO {fmt(fact.get('pdo_year'), '{:.0f}')} · "
                     f"First production {fmt(row.get('start_year'), '{:.0f}')}"
                     + (f" <small>(text: {fact['production_start_text']:.0f})</small>" if pd.notna(fact.get("production_start_text")) else "")),
        ("Development", flags(fact.get("concept") or [])),
    ]
    primary = fact.get("drainage_strategy") or "Not stated"
    mechanisms = [m for m in (fact.get("mechanisms") or []) if m != primary]
    reservoir = [
        ("Drainage strategy", flags([primary] + mechanisms, primary=primary)),
        ("Producing formations", flags(fact.get("formations") or [])),
        ("Groups · age", f"{flags(fact.get('groups') or [])}<br>{escape(', '.join(fact.get('ages') or []) or '—')}"),
        ("Lithology · quality", f"{escape(', '.join(fact.get('lithology') or []) or '—')} · {text(fact.get('reservoir_quality'))}"),
        ("Reservoir depth", depth + (" · <span class='flag primary'>HPHT</span>" if fact.get("hpht") else "")),
        ("Water depth", water),
        ("Pressure · temperature", pt_text),
    ]
    stated = []
    if pd.notna(fact.get("producers_text")):
        stated.append(f"{fact['producers_text']:.0f} producers stated in text")
    if pd.notna(fact.get("injectors_text")):
        stated.append(f"{fact['injectors_text']:.0f} injectors stated in text")
    if pd.notna(fact.get("well_slots_text")):
        stated.append(f"{fact['well_slots_text']:.0f} well slots")
    wells_rows = [
        ("Producers", f"{fmt(row.get('producers_drilled'))} drilled · {fmt(row.get('producers_active'))} active"),
        ("Injectors", f"{fmt(row.get('injectors_drilled'))} drilled · {fmt(row.get('injectors_active'))} active"
                      + f" · ratio {fmt(row.get('injector_producer_ratio'), '{:.2f}')}"),
        ("Observation · subsea · multilateral", f"{fmt(row.get('observation_wells'))} · {fmt(row.get('subsea_share'), '{:.0%}')} · {fmt(row.get('multilateral_share'), '{:.0%}')}"),
        ("Stated in text", escape("; ".join(stated)) if stated else "—"),
    ]
    volumes = [
        ("In place (o.e.)", fmt(row.get("inplace_oe"), "{:,.0f}", " MSm³") + f" <small>oil {fmt(row.get('inplace_oil'))} MSm³ · gas {fmt(row.get('inplace_gas'), '{:,.1f}')} GSm³</small>"),
        ("Recoverable · remaining (o.e.)", f"{fmt(row.get('recoverable_oe'), '{:,.1f}')} · {fmt(row.get('remaining_oe'), '{:,.1f}')} MSm³"),
        ("Recovery factor", f"oil {fmt(row.get('rf_oil'), '{:.0%}')} · gas {fmt(row.get('rf_gas'), '{:.0%}')} · o.e. {fmt(row.get('rf_oe'), '{:.0%}')}"
                            + (f" <small>(text: expected {fact['rf_expected_text']:.0%})</small>" if pd.notna(fact.get("rf_expected_text")) else "")),
        ("Reserve intensity", f"{fmt(row.get('reserves_per_producer'), '{:,.2f}')} MSm³ o.e. per producer · peak offtake {fmt(row.get('peak_offtake_pct'), '{:.1f}')}% of recoverable per year"),
        ("Produced share", f"{fmt(row.get('produced_share_oe'), '{:.0%}')} of recoverable · cumulative water cut {fmt(row.get('cum_water_cut'), '{:.0%}')}"),
    ]
    return identity, reservoir, wells_rows, volumes


def peer_insight(master_subset, env, basis, product_label):
    n = len(master_subset)
    if n == 0:
        return "No fields match the current filters."
    parts = [f"{n} peer fields"]
    if env is not None and not env.empty:
        peak = env.loc[env["p50"].idxmax()]
        unit = {"pct_recoverable": "% of recoverable", "pct_inplace": "% of in place", "per_well": f"{product_label} per well", "absolute": product_label}[basis]
        parts.append(f"median peak of {peak['p50']:,.2f} {unit} per year in year {int(peak['years_on'])} (P10 {peak['p10']:,.2f} – P90 {peak['p90']:,.2f})")
    rf = master_subset["rf_oil"].dropna()
    if len(rf) >= 3:
        parts.append(f"median oil recovery factor {rf.median():.0%}")
    ratio = master_subset["injector_producer_ratio"].dropna()
    if len(ratio) >= 3:
        parts.append(f"median {ratio.median():.2f} injectors per producer")
    return "; ".join(parts) + "."


# ----------------------------------------------------------------------------- sidebar
st.sidebar.markdown("<div class='eyebrow'>Norwegian continental shelf</div>", unsafe_allow_html=True)
st.sidebar.title("Field Intelligence")
st.sidebar.caption("SODIR FactPages · production, reserves, wells and text-derived reservoir facts")
if st.sidebar.button("Refresh SODIR data", width="stretch"):
    load_dataset.clear()
    load_map_layers.clear()
    load_field_geometry.clear()
    compute_master.clear()
    compute_facts.clear()
    st.session_state.pop("data_failures", None)

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
section = st.sidebar.radio("Explore", SECTION_NAMES, key="section")
st.sidebar.divider()
appearance = st.sidebar.selectbox("Appearance", ["Light", "Dark"], key="appearance")
dark = appearance == "Dark"
st.sidebar.caption("Source: Norwegian Offshore Directorate (SODIR). Data cached for one hour; only the active section is loaded.")

palette = theme.css_variables(dark)
st.markdown(
    "<style>:root, .stApp {"
    f"--c-bg:{palette['bg']}; --c-surface:{palette['surface']}; --c-text:{palette['text']}; --c-rule:{palette['rule']};"
    f"--c-muted:{palette['muted']}; --c-accent:{theme.ELECTRIC}; --c-navy:{theme.NAVY};"
    "--background-color: var(--c-bg); --secondary-background-color: var(--c-surface); --text-color: var(--c-text);}"
    + (ROOT / "style.css").read_text(encoding="utf-8")
    + ("[data-testid='stHeader'] {background: transparent;} .stApp input, .stApp [data-baseweb='select'] > div,"
       ".stApp [data-baseweb='input'] > div {background: var(--c-surface); color: var(--c-text);}" if dark else "")
    + "</style>",
    unsafe_allow_html=True,
)

# ----------------------------------------------------------------------------- shared loads
if section in ("Overview", "Production", "Reserves"):
    monthly = optional_dataset("monthly")
    production = select_field(monthly, selected_field, "prfInformationCarrier")
    if not production.empty and production.filter(regex="^prfPrd").isna().any().any():
        st.warning("Some production values are missing. Totals and charts use only reported values.")

# ============================================================================= OVERVIEW
if section == "Overview":
    header("Field profile", selected_field.title(), "Cumulative production, reservoir and development facts extracted from SODIR tables and description texts.")
    metrics = [
        ("Oil", "prfPrdOilNetMillSm3", "million Sm³"),
        ("Gas", "prfPrdGasNetBillSm3", "billion Sm³"),
        ("NGL", "prfPrdNGLNetMillSm3", "million Sm³"),
        ("Condensate", "prfPrdCondensateNetMillSm3", "million Sm³"),
        ("Water", "prfPrdProducedWaterInFieldMillSm3", "million Sm³"),
    ]
    for container, (label, column, unit) in zip(st.columns(5), metrics):
        total = pd.to_numeric(production.get(column, pd.Series(dtype=float)), errors="coerce").sum(min_count=1)
        container.metric(label, f"{total:,.1f}" if pd.notna(total) else "—")
        container.caption(unit)
    if not production.empty:
        st.caption(f"Production data through {production.index.max():%B %Y}.")

    master, facts, pt, tables = get_master()
    identity, reservoir, wells_rows, volumes = field_fact_rows(selected_field, master, facts, pt)
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        st.subheader("Reservoir and recovery")
        st.markdown(facts_html(identity + reservoir), unsafe_allow_html=True)
        st.caption("Formations, depth, drainage strategy and concept are extracted from SODIR description texts by rules; pressure/temperature from the curated table or a depth-based estimate. Verify before decision use.")
    with right:
        st.subheader("Wells and volumes")
        st.markdown(facts_html(wells_rows + volumes), unsafe_allow_html=True)
        url = field_map_url(selected_field, overview)
        if url:
            st.link_button("Open in SODIR FactMaps ↗", url)

    st.subheader("Description")
    sections = sections_for_field(tables["description"], selected_field)
    if not any(sections.values()):
        st.info("No field descriptions available.")
    else:
        for heading in SECTIONS:
            with st.expander(heading):
                st.markdown(sections[heading] or "Not available.")

# ============================================================================= PRODUCTION
elif section == "Production":
    header("Production history", selected_field.title(), "Monthly rates, annual volumes by product, producing-well count, GOR and water cut.")
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

        master, facts, pt, tables = get_master()
        yearly = tables["yearly"]
        if not yearly.empty:
            field_year = bm.yearly_long(yearly)
            field_year = field_year.loc[field_year["fldName"] == selected_field]
            counts = bm.producers_by_year(tables["wells"], CURRENT_YEAR)
            field_year = field_year.merge(counts, on=["fldName", "year"], how="left")
            show_chart(figures.yearly_field_figure(field_year, dark=dark))
            ratio = bm.ratios(yearly, master, CURRENT_YEAR, fields=[selected_field])
            if not ratio.empty:
                c1, c2 = st.columns(2)
                with c1:
                    show_chart(figures.ratio_figure(ratio, "water_cut", master, highlight=selected_field, dark=dark, x_mode="year"))
                with c2:
                    show_chart(figures.ratio_figure(ratio, "gor", master, highlight=selected_field, dark=dark, x_mode="year"))

        st.subheader("Latest 12 months in selected period")
        tail = update_tail_production(filtered, rates=rates)
        columns = st.multiselect("Displayed products", tail.columns, default=tail.columns.tolist())
        st.dataframe(tail[columns], width="stretch")
        st.download_button(
            "Download monthly production CSV",
            filtered.to_csv().encode("utf-8"), file_name=f"{selected_field}_production.csv",
            mime="text/csv",
        )

# ============================================================================= WELLS & RESERVOIR
elif section == "Wells & reservoir":
    header("Wells and reservoir", selected_field.title(), "Development wells by purpose and status, drilling history, and formation tops in the field's wells.")
    master, facts, pt, tables = get_master()
    wells = tables["wells"]
    field_wells = wells.loc[wells["wlbField"] == selected_field] if not wells.empty else pd.DataFrame()
    row = master.loc[selected_field] if selected_field in master.index else pd.Series(dtype=object)
    for container, (label, column) in zip(st.columns(5), (
        ("Producers drilled", "producers_drilled"), ("Producers active", "producers_active"),
        ("Injectors drilled", "injectors_drilled"), ("Injectors active", "injectors_active"),
        ("Reserves per producer", "reserves_per_producer"),
    )):
        value = row.get(column)
        container.metric(label, fmt(value, "{:,.2f}" if column == "reserves_per_producer" else "{:,.0f}"))
    st.caption("Active = SODIR status Producing / Injecting / Online. Reserves per producer in million Sm³ o.e. per drilled production well.")
    if field_wells.empty:
        st.info("No development wells are registered for this field.")
    else:
        show_chart(figures.wells_timeline(field_wells, dark=dark))
        st.subheader("Status by purpose")
        st.dataframe(pd.crosstab(field_wells["wlbStatus"].fillna("—"), field_wells["wlbPurpose"].fillna("—")), width="stretch")
        st.subheader("Well list")
        listing = field_wells[["wlbWellboreName", "wlbPurpose", "wlbStatus", "wlbContent", "wlbCompletionYear",
                               "wlbTotalDepth", "wlbFinalVerticalDepth", "wlbSubSea", "wlbMultilateral", "wlbProductionFacility"]]
        listing = listing.rename(columns=lambda c: c.replace("wlb", ""))
        st.dataframe(listing.sort_values("CompletionYear", ascending=False), width="stretch", hide_index=True)
        st.download_button("Download well list CSV", listing.to_csv(index=False).encode("utf-8"),
                           file_name=f"{selected_field}_wells.csv", mime="text/csv")

        st.subheader("Formation tops in development wells")
        wanted = facts.loc[selected_field, "formations"] if selected_field in facts.index else []
        st.caption("Producing formations from the description text: " + (", ".join(wanted) if wanted else "none extracted") + ". Depths are measured depth (MD RKB) from the SODIR formation-top table.")
        if st.checkbox("Load formation tops for this field's wells (3 MB table)"):
            tops = optional_dataset("tops")
            if not tops.empty:
                field_tops = tops.loc[tops["wlbName"].isin(field_wells["wlbWellboreName"])].copy()
                field_tops["lsuTopDepth"] = pd.to_numeric(field_tops["lsuTopDepth"], errors="coerce")
                field_tops["lsuBottomDepth"] = pd.to_numeric(field_tops["lsuBottomDepth"], errors="coerce")
                if wanted:
                    names = [w.upper() for w in wanted]
                    mask = field_tops["lsuName"].astype("string").str.upper().str.replace(" FM", "", regex=False).isin(names)
                    focus = field_tops.loc[mask]
                else:
                    focus = field_tops.iloc[:0]
                summary_tops = (focus if not focus.empty else field_tops).groupby("lsuName").agg(
                    wells=("wlbName", "nunique"), top_min=("lsuTopDepth", "min"), top_median=("lsuTopDepth", "median"),
                    top_max=("lsuTopDepth", "max"), thickness_median=("lsuBottomDepth", lambda s: float((s - focus.loc[s.index, "lsuTopDepth"]).median()) if not focus.empty else float("nan")),
                ).sort_values("top_median")
                st.dataframe(summary_tops.round(0), width="stretch")
                st.caption(("Rows limited to the extracted producing formations." if not focus.empty else "No extracted formation matched; showing all units."))

# ============================================================================= RESERVES
elif section == "Reserves":
    header("Reserves", selected_field.title(), "Produced volumes against recoverable and in-place estimates.")
    reserves = optional_dataset("reserves")
    inplace = optional_dataset("inplace")
    st.caption(
        "Gauge number: cumulative production. Pale band: remaining reserves. "
        "Accent marker: recoverable volume. Scale: in-place volume or the largest reported value."
    )
    for container, callback in zip(st.columns(2), (callback_plot_reserve, callback_plot_gas)):
        with container:
            show_chart(callback(selected_field, reserves=reserves, inplace=inplace, production=monthly))
    history = select_field(reserves, selected_field)
    if not history.empty and "fldVersion" in history:
        history = history.assign(fldVersion=pd.to_numeric(history["fldVersion"], errors="coerce")).dropna(subset=["fldVersion"]).sort_values("fldVersion")
        fig = go.Figure()
        for column, label, color in (("fldRecoverableOil", "Recoverable oil (MSm³)", theme.NAVY), ("fldRecoverableGas", "Recoverable gas (GSm³)", theme.SKY), ("fldRecoverableOE", "Recoverable o.e. (MSm³)", theme.ELECTRIC)):
            if column in history:
                fig.add_scatter(x=history["fldVersion"], y=pd.to_numeric(history[column], errors="coerce"), mode="lines+markers", name=label, line=dict(color=color))
        fig.update_layout(xaxis_title="Estimate year", yaxis_title="Volume")
        show_chart(theme.style(fig, "Reserves revisions over time", "SODIR annual resource accounts", dark=dark, height=420))

# ============================================================================= INVESTMENTS
elif section == "Investments":
    header("Investments", selected_field.title())
    show_chart(callback_investments(selected_field, optional_dataset("investments")))

# ============================================================================= MAP
elif section == "Map":
    header("Map", selected_field.title())
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
                map_document(selected_field, geometry, {key: catalogue[key] for key in selected_layers}, dark=dark),
                height=565,
            )
            st.caption("Layers come from SODIR's live WMS catalogue. Accent boundaries / points come from its field geometry service. Only selected overlays request tiles.")
            rendered = True
        except DataUnavailable as exc:
            st.warning(f"{exc} Showing the official viewer instead.")
    if url:
        if not rendered:
            st.iframe(url, height=560)
        st.link_button("Open selected field in FactMaps ↗", url)
    else:
        st.info("No valid SODIR map identifier is available for this field.")

# ============================================================================= BENCHMARK
elif section == "Benchmark":
    header("Benchmark", "How does the field compare with its peers?",
           "Normalised production profiles, reserve intensity, recovery factors, well counts and GOR / water-cut development across NCS fields. "
           "Filter the peer set by formation, drainage strategy, hydrocarbon phase and volumes; import your own profile or generate an average profile.")

    with st.container(border=True):
        c1, c2, c3, c4, c5 = st.columns([1, 1.4, 1, 1, 1])
        product_label = c1.selectbox("Product", list(bm.PRODUCTS), key="bm_product")
        product = bm.PRODUCTS[product_label]
        basis_label = c2.selectbox("Normalisation", list(bm.BASES), index=2, key="bm_basis")
        basis = bm.BASES[basis_label]
        x_mode = c3.selectbox("X-axis", ["Years since start", "Calendar year"], key="bm_x")
        x_mode = "years_on" if x_mode.startswith("Years") else "year"
        color_key = c4.selectbox("Colour by", list(bm.COLOR_OPTIONS), index=1, key="bm_color")
        color_column = bm.COLOR_OPTIONS[color_key]
        start_threshold = c5.selectbox("Start year = first year ≥", ["any production", "5% of peak", "10% of peak", "25% of peak"], index=1, key="bm_start")
        start_threshold = {"any production": 0.0, "5% of peak": 0.05, "10% of peak": 0.10, "25% of peak": 0.25}[start_threshold]

    master, facts, pt, tables = get_master(start_threshold)
    yearly, wells = tables["yearly"], tables["wells"]
    if master.empty or yearly.empty:
        st.info("Benchmarking needs the SODIR field, reserves and yearly production tables.")
        st.stop()

    with st.expander("Peer-set filters", expanded=True):
        f1, f2, f3, f4 = st.columns(4)
        hc_types = f1.multiselect("Hydrocarbon phase", sorted(master["hc_type"].dropna().unique()), key="bm_hc")
        areas = f2.multiselect("Area", sorted(master["area"].dropna().unique()), key="bm_area")
        drives = f3.multiselect("Drainage strategy", sorted(master["drainage_strategy"].dropna().unique()), key="bm_drive")
        statuses = f4.multiselect("Status", sorted(master["status"].dropna().astype(str).unique()), key="bm_status")
        g1, g2, g3, g4 = st.columns(4)
        formation_options = sorted({f for v in master.get("formations", pd.Series(dtype=object)) for f in (v or [])})
        group_options = sorted({g for v in master.get("groups", pd.Series(dtype=object)) for g in (v or [])})
        lith_options = sorted({g for v in master.get("lithology", pd.Series(dtype=object)) for g in (v or [])})
        formations_sel = g1.multiselect("Producing formation", formation_options, key="bm_fm")
        groups_sel = g2.multiselect("Group", group_options, key="bm_gp")
        lith_sel = g3.multiselect("Lithology", lith_options, key="bm_lith")
        hpht_sel = g4.selectbox("Pressure regime", ["All", "Normal only", "HPHT only"], key="bm_hpht")
        h1, h2, h3, h4 = st.columns(4)
        max_inplace = ceil_ten(master["inplace_oe"].max())
        inplace_range = h1.slider("In-place volume · million Sm³ o.e.", 0.0, max_inplace, (0.0, max_inplace), key="bm_inplace")
        max_rec = ceil_ten(master["recoverable_oe"].max())
        rec_range = h2.slider("Recoverable · million Sm³ o.e.", 0.0, max_rec, (0.0, max_rec), key="bm_rec")
        years = master["start_year"].dropna()
        y_min, y_max = (int(years.min()), int(years.max())) if not years.empty else (1970, CURRENT_YEAR)
        start_range = h3.slider("Production start year", y_min, max(y_max, y_min + 1), (y_min, max(y_max, y_min + 1)), key="bm_startrange")
        min_years = h4.number_input("Minimum years on production", 0, 60, 3, key="bm_minyears")
        include_missing = st.checkbox("Keep fields without in-place / recoverable data in the peer set", value=True, key="bm_missing")

    mask = bm.apply_filters(
        master, hc_types=hc_types, areas=areas, drives=drives, formations=formations_sel, groups=groups_sel,
        statuses=statuses, inplace_range=inplace_range, recoverable_range=rec_range, start_range=start_range,
        min_years=int(min_years), hpht={"All": None, "Normal only": False, "HPHT only": True}[hpht_sel],
        lithologies=lith_sel, include_missing=include_missing,
    )
    peers = master.loc[mask]
    peer_fields = list(peers.index)
    highlight = selected_field if selected_field in peers.index else None
    if selected_field not in peers.index:
        st.caption(f"{selected_field.title()} is outside the current peer set; it is not highlighted.")

    profiles = bm.normalised_profiles(yearly, master, product, basis, wells=wells, current_year=CURRENT_YEAR, fields=peer_fields)
    env = bm.envelope(profiles)
    unit = bm.PRODUCT_UNITS[product]
    y_label = {"absolute": f"{product_label} · {unit} per year", "per_well": f"{product_label} · {unit} per producing well per year",
               "pct_recoverable": f"% of recoverable {product_label.lower()} per year", "pct_inplace": f"% of in-place {product_label.lower()} per year"}[basis]
    st.markdown(f"<p class='lede'><b>{escape(peer_insight(peers, env, basis, unit))}</b></p>", unsafe_allow_html=True)

    tabs = st.tabs(["Production profiles", "Reserve intensity", "Recovery factor", "Producers vs injectors",
                    "GOR & water cut", "Compare & type curve", "Reservoir P/T", "Peer table"])

    with tabs[0]:
        o1, o2 = st.columns([1, 1])
        show_lines = o1.checkbox("Show individual field profiles", value=True, key="bm_lines")
        log_y = o2.checkbox("Logarithmic y-axis", value=False, key="bm_log")
        show_chart(figures.profile_figure(
            profiles, env, master, color_key, color_column, highlight=highlight, x_mode=x_mode, y_label=y_label,
            title=f"{basis_label} · {product_label.lower()}", subtitle=f"Peer set of {len(peer_fields)} fields · band = P10–P90 across fields in the same production year",
            dark=dark, show_lines=show_lines, log_y=log_y,
        ))
        if not env.empty:
            e1, e2 = st.columns([2, 1])
            e1.dataframe(env.round(3).rename(columns={"years_on": "Year", "n": "Fields"}), width="stretch", hide_index=True, height=260)
            e2.download_button("Download envelope CSV", env.to_csv(index=False).encode("utf-8"), file_name="benchmark_envelope.csv", mime="text/csv")
            e2.download_button("Download normalised profiles CSV", profiles.to_csv(index=False).encode("utf-8"), file_name="benchmark_profiles.csv", mime="text/csv")
        st.caption("Current calendar year is excluded as a partial year. Per-well values use production wells completed and not yet plugged; fields with unreported abandonments are conservative.")

    with tabs[1]:
        st.markdown("Reserve intensity: how much recoverable volume each production well carries, and how hard the field is produced relative to its reserves.")
        i1, i2 = st.columns(2)
        with i1:
            show_chart(figures.box_by_category(peers, "reserves_per_producer", color_column, "Recoverable o.e. per drilled producer", "million Sm³ o.e. per producer", highlight=highlight, dark=dark, color_key=color_key, log=True))
        with i2:
            show_chart(figures.box_by_category(peers, "peak_offtake_pct", color_column, "Peak annual offtake as share of recoverable", "% of recoverable per year", highlight=highlight, dark=dark, color_key=color_key))
        i3, i4 = st.columns(2)
        with i3:
            show_chart(figures.box_by_category(peers, "inplace_per_producer", color_column, "In-place o.e. per drilled producer", "million Sm³ o.e. per producer", highlight=highlight, dark=dark, color_key=color_key, log=True))
        with i4:
            show_chart(figures.box_by_category(peers, "years_to_peak", color_column, "Years from start to peak production", "years", highlight=highlight, dark=dark, color_key=color_key, fmt=":.0f"))

    with tabs[2]:
        rf_product = st.radio("Recovery factor of", ["oil", "gas", "oe"], horizontal=True, format_func=lambda v: {"oil": "Oil", "gas": "Gas", "oe": "Oil equivalent"}[v], key="bm_rf")
        implausible = int((peers[f"rf_{rf_product}_raw"] > 1.0).sum())
        if implausible:
            st.caption(f"{implausible} field(s) excluded with recoverable > in place (SODIR books condensate as recoverable oil for some gas fields): "
                       + ", ".join(f.title() for f in peers.index[peers[f"rf_{rf_product}_raw"] > 1.0]))
        show_chart(figures.rf_scatter(peers, rf_product, color_key, color_column, highlight=highlight, dark=dark))
        r1, r2 = st.columns([1.3, 1])
        with r1:
            show_chart(figures.rf_bars(peers, rf_product, color_key, color_column, highlight=highlight, dark=dark))
        with r2:
            show_chart(figures.box_by_category(peers, f"rf_{rf_product}", color_column, f"Recovery factor by {color_key.lower()}", "Recovery factor", highlight=highlight, dark=dark, color_key=color_key, fmt=":.0%"))
            stated = peers.dropna(subset=["rf_expected_text"]) if "rf_expected_text" in peers else pd.DataFrame()
            if not stated.empty:
                st.markdown("**Recovery factors stated in SODIR text**")
                st.dataframe(stated[["rf_initial_text", "rf_expected_text", f"rf_{rf_product}"]].rename(columns={"rf_initial_text": "Initial (text)", "rf_expected_text": "Expected (text)", f"rf_{rf_product}": "Computed"}).style.format("{:.0%}", na_rep="—"), width="stretch")

    with tabs[3]:
        active = st.toggle("Active wells only (instead of all drilled)", value=False, key="bm_active")
        show_chart(figures.wells_scatter(peers, color_key, color_column, highlight=highlight, dark=dark, active=active))
        w1, w2 = st.columns(2)
        with w1:
            show_chart(figures.box_by_category(peers, "injector_producer_ratio", color_column, "Injectors per producer", "injectors ÷ producers (drilled)", highlight=highlight, dark=dark, color_key=color_key))
        with w2:
            show_chart(figures.box_by_category(peers, "producers_drilled", color_column, "Production wells drilled", "wells", highlight=highlight, dark=dark, color_key=color_key, log=True, fmt=":.0f"))

    with tabs[4]:
        metric = st.radio("Metric", ["water_cut", "gor", "gas_share", "cgr"], horizontal=True,
                          format_func=lambda v: {"water_cut": "Water cut", "gor": "GOR", "gas_share": "Gas share of o.e.", "cgr": "Condensate-gas ratio"}[v], key="bm_metric")
        ratio = bm.ratios(yearly, master, CURRENT_YEAR, fields=peer_fields)
        show_chart(figures.ratio_figure(ratio, metric, master, color_key, color_column, highlight=highlight, dark=dark, x_mode=x_mode))
        st.caption("GOR = annual gas ÷ annual oil (Sm³/Sm³). Water cut = produced water ÷ (water + oil). SODIR reports produced water only for recent decades, so early-life water cut may be blank.")

    with tabs[5]:
        st.markdown("Import a production profile (CSV or Excel with a `year` column and any of `oil` [million Sm³], `gas` [billion Sm³], `water`, `wells`) to overlay it on the peer envelope, or generate an average profile from the peer set scaled to your volumes.")
        u1, u2 = st.columns([1, 1])
        with u1:
            upload = st.file_uploader("Profile file", type=["csv", "xlsx", "xls"], key="bm_upload")
            template = "year,oil,gas,water,wells\n2030,0.8,0.3,0.0,3\n2031,2.4,0.9,0.1,6\n2032,2.3,0.9,0.4,6\n2033,1.9,0.8,0.9,6\n"
            st.download_button("Download CSV template", template.encode("utf-8"), file_name="profile_template.csv", mime="text/csv")
        with u2:
            own_recoverable = st.number_input(f"Recoverable {product_label.lower()} of your case · {unit}", min_value=0.0, value=float(peers["recoverable_oe"].median() if peers["recoverable_oe"].notna().any() else 50.0), key="bm_rec_own")
            own_inplace = st.number_input(f"In-place {product_label.lower()} of your case · {unit}", min_value=0.0, value=0.0, key="bm_inplace_own")
            own_start = st.number_input("First production year", min_value=1970, max_value=2100, value=CURRENT_YEAR + 3, key="bm_start_own")
            statistic = st.selectbox("Average profile statistic", ["p50", "mean", "p10", "p90"], key="bm_stat")
            rescale = st.checkbox("Rescale so the cumulative equals the stated volume", value=True, key="bm_rescale")
        uploaded_norm = None
        if upload is not None:
            try:
                profile = bm.parse_profile_upload(upload.getvalue(), upload.name)
                uploaded_norm = bm.normalise_upload(profile, product, basis, recoverable=own_recoverable or None, inplace=own_inplace or None)
                if uploaded_norm.empty:
                    st.warning("The imported profile could not be normalised on this basis (missing wells or volumes).")
                st.dataframe(profile, width="stretch", hide_index=True, height=200)
            except (ValueError, ImportError) as exc:
                st.error(f"Could not read the profile: {exc}")
        show_chart(figures.profile_figure(
            profiles, env, master, color_key, color_column, highlight=highlight, upload=uploaded_norm, x_mode="years_on",
            y_label=y_label, title="Imported profile against the peer envelope", subtitle=f"{basis_label} · {len(peer_fields)} peers", dark=dark,
            show_lines=False,
        ))
        if basis in ("pct_recoverable", "pct_inplace"):
            scale = own_inplace if basis == "pct_inplace" else own_recoverable
            curve = bm.type_curve(env, scale, int(own_start), statistic, basis, rescale=rescale)
            if not curve.empty:
                st.markdown(f"**Average profile ({statistic.upper()}) scaled to {scale:,.1f} {unit}** — cumulative {curve['cumulative'].iloc[-1]:,.1f} {unit} over {len(curve)} years.")
                t1, t2 = st.columns([2, 1])
                t1.dataframe(curve.round(3).rename(columns={"pct": "% per year", "value": unit, "cumulative": f"cumulative {unit}"}), width="stretch", hide_index=True, height=260)
                t2.download_button("Download average profile CSV", curve.to_csv(index=False).encode("utf-8"), file_name="average_profile.csv", mime="text/csv")
                t2.caption("The envelope stops where fewer than three peers have data, so long tails are truncated; extend with a decline if needed.")
        else:
            st.caption("Choose a percentage normalisation (% of recoverable or % of in place) to generate a scaled average profile.")

    with tabs[6]:
        st.markdown("SODIR publishes no pressure/temperature table. Values come from, in order: your uploaded table, the built-in curated literature table, numbers stated in the SODIR text, or a hydrostatic (0.101 bar/m) and geothermal (4 °C + 35 °C/km) estimate from the text depth. HPHT fields never receive a pressure estimate.")
        show_chart(figures.pt_figure(peers, highlight=highlight, dark=dark))
        p1, p2 = st.columns([1.3, 1])
        with p1:
            table = peers[["depth_mid_m", "pressure_bar", "temperature_c", "pt_confidence", "pt_source", "hpht"]].rename(columns={"depth_mid_m": "Depth m", "pressure_bar": "Pressure bar", "temperature_c": "Temperature °C", "pt_confidence": "Confidence", "pt_source": "Source", "hpht": "HPHT"})
            st.dataframe(table.sort_values("Confidence"), width="stretch", height=360)
        with p2:
            st.download_button("Download curated P/T table", load_curated().to_csv(index=False).encode("utf-8"), file_name="reservoir_pt.csv", mime="text/csv")
            pt_upload = st.file_uploader("Upload your own P/T table (CSV: field, pressure_bar, temperature_c, …)", type=["csv"], key="bm_pt_upload")
            if pt_upload is not None:
                try:
                    user_pt = normalise_pt(pd.read_csv(pt_upload))
                    st.session_state["user_pt"] = user_pt
                    st.success(f"{len(user_pt)} rows loaded for this session. Values override the curated table.")
                except (ValueError, pd.errors.ParserError) as exc:
                    st.error(f"Could not read the table: {exc}")
            if st.session_state.get("user_pt") is not None and st.button("Clear uploaded P/T table"):
                st.session_state.pop("user_pt")
                st.rerun()

    with tabs[7]:
        columns = ["hc_type", "area", "status", "drainage_strategy", "formations_text", "groups_text", "main_age", "main_lithology",
                   "depth_mid_m", "hpht", "pressure_bar", "temperature_c", "start_year", "years_on_production", "peak_year", "cum_oe",
                   "recoverable_oe", "remaining_oe", "inplace_oe", "rf_oil", "rf_gas", "rf_oe", "producers_drilled", "producers_active",
                   "injectors_drilled", "injectors_active", "injector_producer_ratio", "reserves_per_producer", "peak_offtake_pct",
                   "cum_water_cut", "concept_text", "sub_area", "operator"]
        table = peers[[c for c in columns if c in peers]]
        st.dataframe(table, width="stretch", height=520)
        st.download_button("Download peer table CSV", table.to_csv().encode("utf-8"), file_name="benchmark_peers.csv", mime="text/csv")

# ============================================================================= DATA & QA
elif section == "Data & QA":
    header("Data & QA", "How much of the picture is covered?", "Coverage of each attribute across fields, and the extraction audit for the selected field.")
    master, facts, pt, tables = get_master()
    cov = bm.coverage(master, ["start_year", "recoverable_oe", "inplace_oe", "rf_oil", "rf_gas", "producers_drilled", "injectors_drilled",
                               "drainage_strategy", "formations", "groups", "ages", "depth_mid_m", "water_depth_min_m", "concept",
                               "discovery_year", "pdo_year", "producers_text", "pressure_bar", "temperature_c"])
    if not cov.empty:
        st.dataframe(cov.assign(share=cov["share"].map("{:.0%}".format)), width="stretch", hide_index=True)
    st.subheader(f"Extraction audit · {selected_field.title()}")
    if selected_field in facts.index:
        audit = facts.loc[selected_field].to_dict()
        st.json({k: (v if not isinstance(v, float) or pd.notna(v) else None) for k, v in audit.items()}, expanded=False)
    sections = sections_for_field(tables["description"], selected_field)
    for heading in SECTIONS:
        with st.expander(f"Source text · {heading}"):
            st.write(sections[heading] or "Not available.")
    st.subheader("Method notes")
    st.markdown(
        "- **Drainage strategy** is the mechanism in the sentence that states how the field is produced; secondary mechanisms are listed as flags.\n"
        "- **Formations / groups / ages** are proper names preceding *Formation* / *Group* and standard chronostratigraphic terms in the Reservoir text.\n"
        "- **Depth** is the reservoir depth sentence (water-depth sentences are excluded); the mid-point drives the P/T estimate.\n"
        "- **Well counts** come from the SODIR development-wellbore table (purpose and status); counts stated in the text are shown separately.\n"
        "- **Recovery factor** = latest recoverable ÷ in-place volume per product; produced share = cumulative production ÷ recoverable.\n"
        "- **Reserve intensity** = recoverable o.e. per drilled production well; peak offtake = peak annual o.e. ÷ recoverable o.e."
    )
