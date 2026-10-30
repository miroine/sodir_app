"""Portfolio workspace UI; independent of the selected field and field controls."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils import portfolio as pf, theme, ukcs
from utils.data import DataUnavailable
from utils.investments import prepare_investments


def chart(data, metric, title, unit, companies, dark, index=False):
    fig = go.Figure()
    for number, (company, part) in enumerate(data.loc[data["company"].isin(companies)].groupby("company")):
        part = part.sort_values("year")
        name = f"{part.iloc[0]['company_name']} · {company.split('::', 1)[0]}"
        part = part.set_index("year").reindex(range(int(part["year"].min()), int(part["year"].max()) + 1))
        fig.add_scatter(x=part.index, y=part[metric], name=name, mode="lines+markers",
                        connectgaps=False, line=dict(color=theme.SEQUENCE[number % len(theme.SEQUENCE)]),
                        hovertemplate="%{x:.0f}: %{y:,.2f}<extra>%{fullData.name}</extra>")
    fig.update_layout(xaxis=dict(title="Calendar year", tickformat="d"), yaxis_title=unit)
    if index:
        fig.add_hline(y=100, line_dash="dot", line_color=theme.GREY)
    st.plotly_chart(theme.style(fig, title, "Current-equity restatement · reported legal licensees",
                              "SODIR + NSTA; uploaded forecasts where selected", dark=dark), width="stretch", theme=None)


def download(label, data, filename):
    st.download_button(label, data.to_csv(index=False).encode("utf-8"), filename, "text/csv")


def selection(label, options, key, **kwargs):
    if key in st.session_state:
        st.session_state[key] = [value for value in st.session_state[key] if value in options]
    return st.multiselect(label, options, key=key, **kwargs)


def clear_forecast_upload():
    st.session_state.pop("portfolio_upload", None)
    st.session_state.pop("pf_upload", None)


def render(dark, current_year, load_ncs):
    st.markdown("<div class='eyebrow'>Company intelligence · current equity</div>", unsafe_allow_html=True)
    st.title("Portfolio")
    st.markdown("Compare equity-attributed production, annual field CAPEX and future production across companies and North Sea regions.")
    st.warning("Ownership basis: current published interests are applied to all displayed years and forecasts. "
               "This is a current-portfolio restatement, NOT actual historical company production, company accounts or net entitlement. "
               "Legal licensees remain separate; parent groups and cross-border subsidiaries are not silently merged.")
    countries = st.multiselect("Portfolio countries", ["NCS", "UKCS"], default=["NCS", "UKCS"], key="pf_countries")
    snapshot = pd.Timestamp.now(tz="UTC").date()
    metadata, production, costs, interests = [], [], [], []
    for country in countries:
        try:
            if country == "NCS":
                fields = pf.field_metadata(load_ncs("overview"), country)
                yearly = load_ncs("yearly").copy()
                yearly["prfInformationCarrier"] = "NCS::" + yearly["prfInformationCarrier"].astype(str)
                try:
                    interests.append(pf.ncs_equity(load_ncs("equity"), snapshot))
                except (DataUnavailable, ValueError) as exc:
                    st.error(f"NCS ownership unavailable; fields cannot be equity-attributed: {exc}")
                try:
                    investment = prepare_investments(load_ncs("investments"), current_year)
                    investment["fldName"] = "NCS::" + investment["fldName"].astype(str)
                    costs.append(investment)
                except (DataUnavailable, ValueError) as exc:
                    st.warning(f"NCS field CAPEX unavailable; CAPEX metrics are incomplete: {exc}")
            else:
                fields = pf.field_metadata(ukcs.load_fields(), country)
                yearly = ukcs.load_yearly()
                try:
                    ownership = pf.load_uk_ownership()
                    interests.append(pf.uk_equity(ownership, snapshot))
                    try:
                        fields["region"] = pf.uk_regions(ownership, pf.load_uk_region_polygons()).reindex(fields.index)
                    except (DataUnavailable, KeyError, ValueError) as exc:
                        st.warning(f"UK map regions unavailable; retaining fields as unclassified: {exc}")
                except (DataUnavailable, KeyError, ValueError) as exc:
                    st.error(f"UK ownership unavailable; fields cannot be equity-attributed: {exc}")
            metadata.append(fields)
            production.append(yearly)
        except (DataUnavailable, ValueError) as exc:
            st.error(f"{country} portfolio production/catalogue unavailable; requested country is excluded: {exc}")
    if not metadata:
        st.info("Select at least one country with available field and production data.")
        return
    fields = pd.concat(metadata)
    cost = pd.concat(costs, ignore_index=True) if costs else pd.DataFrame(columns=["fldName", "year", "nominal_mnok"])
    history = pf.field_history(pd.concat(production, ignore_index=True), cost, fields, current_year)
    equity_raw = pd.concat(interests, ignore_index=True) if interests else pd.DataFrame(columns=pf.EQUITY_COLUMNS)
    equity, ownership_qa = pf.validate_equity(equity_raw, fields)
    st.caption(f"Ownership snapshot evaluated/retrieved {snapshot}. UK equity is integer-valued in the source; "
               "partial totals remain unallocated, never scaled to 100%. Source snapshots can lag effective transactions. "
               "CAPEX is nominal million NOK; no comparable connected UK field CAPEX. Cost intensity is NOK/boe, not operating cost or oil-only cost.")
    st.caption("Regions: SODIR main sea areas for NCS; NSTA regional-map polygons containing the UK field centroid. "
               "These are geographic reporting filters, not equivalent geological basins. Unclassified/boundary fields remain visible.")
    regions = selection("Regions / sea areas", sorted(fields["region"].dropna().unique()), "pf_regions",
                        help="Empty selection includes every region, including unclassified fields.")
    if regions:
        fields = fields.loc[fields["region"].isin(regions)]
    company_names = equity.drop_duplicates("company").set_index("company")["company_name"]
    eligible = sorted(equity.loc[equity["fldName"].isin(fields.index), "company"].unique())
    companies = selection("Companies (legal licensees)", eligible, "pf_companies",
                          format_func=lambda key: f"{company_names[key]} · {key.split('::', 1)[0]}",
                          help="Empty selection includes every available licensee. Subsidiaries remain separate.")
    equity = equity.loc[equity["fldName"].isin(fields.index)]
    if companies:
        equity = equity.loc[equity["company"].isin(companies)]
        fields = fields.loc[fields.index.isin(equity["fldName"])]
    history = history.loc[history["fldName"].isin(fields.index)]
    if fields.empty or history.empty:
        st.info("No field history matches the selected regions and companies.")
        return
    years = sorted(history["year"].unique().tolist())
    c1, c2, c3 = st.columns(3)
    if st.session_state.get("pf_cutoff") not in years:
        st.session_state.pop("pf_cutoff", None)
    cutoff = c1.selectbox("History / forecast cutoff year", years, index=len(years) - 1, key="pf_cutoff")
    start_options = [year for year in years if year <= cutoff]
    if st.session_state.get("pf_start") not in start_options:
        st.session_state.pop("pf_start", None)
    start = c2.selectbox("History starts", start_options, index=max(0, len(start_options) - 10), key="pf_start")
    horizon = c3.number_input("Forecast years", 1, 30, 10, key="pf_horizon")
    period = history.loc[history["year"].between(start, cutoff)]
    ledger = pf.allocate(period, equity)
    annual = pf.company_annual(ledger)
    summary = pf.company_summary(annual)
    if not annual.empty:
        expected = equity.groupby("company")["fldName"].nunique()
        annual["selected_equity_fields"] = annual["company"].map(expected)
        annual["production_field_coverage_pct"] = 100 * annual["fields_with_production"] / annual["selected_equity_fields"]
        annual["matched_field_coverage_pct"] = 100 * annual["matched_fields"] / annual["selected_equity_fields"]
        for table in (annual, summary):
            table["snapshot_date"] = str(snapshot)
            table["attribution_basis"] = "Current published equity restated across all displayed years"
    excluded = len(fields.index.difference(equity["fldName"]))
    st.caption(f"{len(fields)} selected fields; {equity['company'].nunique()} legal licensees; "
               f"{excluded} fields without usable current interests. Missing ownership, production and costs are not filled with zero.")
    if annual.empty:
        st.info("No usable equity allocations for this peer set. Inspect ownership coverage below.")
        st.dataframe(fields.join(ownership_qa), width="stretch")
        return
    cols = st.columns(3)
    for container, (label, column, suffix) in zip(cols, (
        ("Attributed production · selected period", "production_mboe", "million boe"),
        ("Attributed field CAPEX · selected period", "nominal_mnok", "million NOK"),
        ("Matched CAPEX intensity", "capex_nok_boe", "NOK/boe"),
    )):
        if column == "capex_nok_boe":
            denominator = summary["matched_production_mboe"].sum(min_count=1)
            value = summary["matched_capex_mnok"].sum(min_count=1) / denominator if pd.notna(denominator) and denominator > 0 else float("nan")
        else:
            value = summary[column].sum(min_count=1)
        container.metric(label, f"{value:,.2f}" if pd.notna(value) else "Unavailable")
        container.caption(suffix)
    count = st.number_input("Maximum companies plotted", 1, 50, 10, key="pf_plot_count")
    plotted = summary.sort_values("production_mboe", ascending=False)["company"].head(count).tolist()
    st.caption("Charts show the largest selected companies by historical attributed production. Tables/downloads retain all selected companies. "
               "Select individual companies above to compare smaller portfolios.")
    tabs = st.tabs(["Production", "CAPEX & intensity", "Future production", "Coverage & downloads"])
    with tabs[0]:
        chart(annual, "production_mboe", "Annual equity-attributed production", "Million boe/year", plotted, dark)
        chart(annual, "oil_mmbbl", "Annual equity-attributed oil", "Million oil barrels/year", plotted, dark)
        chart(annual, "gas", "Annual equity-attributed gas", "Billion Sm³/year · UK pipeline gas; NCS net gas", plotted, dark)
        st.caption("Cross-country production basis differs: UK uses pipeline gas and an OE proxy excluding separate NGL; "
                   "NCS uses SODIR net products and reported OE. Surface-volume conversion: 6.28981 boe per Sm³ OE. "
                   "These are not energy-content-adjusted company entitlement volumes.")
        st.dataframe(summary, hide_index=True, width="stretch")
    with tabs[1]:
        st.info("CAPEX is field investment × current equity, not reported company spending. UK cost data are unavailable. "
                "CAPEX/boe uses only identical field-year pairs with BOTH reported CAPEX and production, "
                "including reported zero production. It is a ratio of sums, not an average of field ratios. "
                "Preproduction CAPEX without a reported production row remains unmatched. Check matched fields before ranking companies.")
        chart(annual, "nominal_mnok", "Annual equity-attributed field CAPEX", "Nominal million NOK/year", plotted, dark)
        chart(annual, "capex_nok_boe", "Matched annual CAPEX per produced boe", "NOK/boe · matched field-years only", plotted, dark)
        st.dataframe(annual, hide_index=True, width="stretch")
    with tabs[2]:
        st.warning("Screening scenario, not an official prognosis: fit only the main phase over up to five recent consecutive years, "
                   "derive other products by fixed window-total ratios, then sum field forecasts × current equity. "
                   "Rising, incomplete or stale histories are excluded, not forced into decline. No new developments, reserve constraints, "
                   "economic cessation, acquisitions or company tax assumptions are invented. UK NGL stays unavailable.")
        phase = st.selectbox("Main phase for automatic field fits", ["Auto", "oil", "gas", "condensate", "ngl"], key="pf_phase")
        st.caption("Upload CSV/XLSX: country,field,year,oil,gas,condensate,ngl. Liquids: million Sm³; gas: billion Sm³ "
                   "(pipeline gas for UK). NCS requires ngl; UK ngl must be blank. Provide the complete selected future horizon "
                   "per overridden field; explicit zeros represent cessation. Uploads are gross field volumes, before equity.")
        template = pd.DataFrame([dict(country=fields.iloc[0]["country"], field=fields.iloc[0]["field_name"],
                                      year=year, oil=0, gas=0, condensate=0,
                                      ngl=0 if fields.iloc[0]["country"] == "NCS" else None)
                                 for year in range(cutoff + 1, cutoff + horizon + 1)])
        download("Download forecast input template (zeros to replace)", template, "portfolio_forecast_template.csv")
        upload = st.file_uploader("Field forecast overrides", type=["csv", "xlsx"], key="pf_upload")
        if upload is not None:
            st.session_state["portfolio_upload"] = (upload.name, upload.getvalue())
        retained = st.session_state.get("portfolio_upload")
        if retained:
            st.caption(f"Retained portfolio forecast: {retained[0]}")
            st.button("Clear portfolio forecast", key="pf_clear_upload", on_click=clear_forecast_upload)
        overrides = None
        valid_upload = True
        if retained:
            try:
                # Validate against the loaded catalogue, not the current company/region filter.
                overrides = pf.parse_forecasts(retained[1], retained[0], pd.concat(metadata), cutoff, horizon)
                matched_fields = overrides.loc[overrides["fldName"].isin(fields.index), "fldName"].nunique()
                st.success(f"Uploaded forecasts accepted for {overrides['fldName'].nunique()} fields; "
                           f"{matched_fields} match the selected portfolio and replace their automatic fits.")
            except (ValueError, pd.errors.ParserError) as exc:
                st.error(f"Forecast overrides rejected; no forecast is displayed until corrected or cleared: {exc}")
                valid_upload = False
        if valid_upload:
            future, fit_qa = pf.forecast_fields(history, fields, cutoff, horizon, overrides,
                                              None if phase == "Auto" else phase)
            future_company, future_ledger = pf.forecast_companies(future, history, equity, cutoff)
            if not future_company.empty:
                future_company["snapshot_date"] = str(snapshot)
                future_company["attribution_basis"] = "Current published equity restated across all forecast years"
            st.caption(f"Forecast fields included: {int(fit_qa['forecast_status'].eq('Included').sum())}/{len(fit_qa)}. "
                       "These totals cover only fitted/uploaded fields; exclusions are not zero production. "
                       "Indexed forecasts use cutoff production from the SAME included field set; missing baselines suppress the index.")
            if not future_company.empty:
                chart(future_company, "production_mboe", "Company future equity production", "Million boe/year", plotted, dark)
                chart(future_company, "production_index", "Future production benchmark · matched fields",
                      f"{cutoff} matched production = 100", plotted, dark, index=True)
                st.dataframe(future_company, hide_index=True, width="stretch")
                endpoint = future_company.loc[future_company["year"].eq(cutoff + horizon)].copy()
                endpoint["country"] = endpoint["company"].str.split("::").str[0]
                endpoint["change_from_matched_cutoff_pct"] = endpoint["production_index"] - 100
                endpoint = endpoint.sort_values("production_mboe", ascending=False)
                st.markdown("**End-horizon company benchmark** — compare absolute scale, matched-field growth and forecast coverage together.")
                st.dataframe(endpoint[["company_name", "country", "production_mboe", "change_from_matched_cutoff_pct",
                                       "forecast_baseline_coverage_pct", "forecast_field_count"]], hide_index=True, width="stretch")
                download("Download company forecast CSV", future_company, "portfolio_company_forecast.csv")
                download("Download allocated field forecasts CSV", future_ledger, "portfolio_field_forecasts.csv")
            else:
                st.info("No equity-attributable field forecasts. Review exclusions, select a different cutoff/main phase or upload a prognosis.")
            st.dataframe(fields.join(fit_qa), width="stretch")
            download("Download field forecast coverage CSV", fields.join(fit_qa).reset_index(), "portfolio_forecast_coverage.csv")
    with tabs[3]:
        coverage = fields.join(ownership_qa)
        coverage["production_years_in_period"] = period.loc[period["production_mboe"].notna()].groupby("fldName").size().reindex(fields.index, fill_value=0)
        coverage["capex_years_in_period"] = period.loc[period["nominal_mnok"].notna()].groupby("fldName").size().reindex(fields.index, fill_value=0)
        coverage["snapshot_date"] = str(snapshot)
        st.dataframe(coverage, width="stretch")
        st.dataframe(equity_raw.loc[equity_raw["fldName"].isin(fields.index)], hide_index=True, width="stretch")
        download("Download portfolio coverage CSV", coverage.reset_index(), "portfolio_coverage.csv")
        download("Download company annual CSV", annual, "portfolio_company_annual.csv")
        download("Download company summary CSV", summary, "portfolio_company_summary.csv")
        download("Download equity allocation ledger CSV", ledger, "portfolio_equity_ledger.csv")
        download("Download published equity interests CSV", equity_raw.loc[equity_raw["fldName"].isin(fields.index)],
                 "portfolio_equity_interests.csv")
        st.markdown(f"[SODIR field licensee history]({pf.NCS_EQUITY_SOURCE}) · "
                    f"[NSTA field licensees/equity]({ukcs.FIELDS}) · [NSTA map regions]({pf.UK_REGIONS})")
