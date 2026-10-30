import json
from io import BytesIO
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from utils import ukcs, benchmark as bm, figures
from utils.data import DataUnavailable
from test_dashboard import datasets, ROOT
from utils.maps import map_document

LOAD_MAP_CONTEXT = ukcs.load_map_context.__wrapped__


def test_units_and_missing_ngl_are_not_zero_filled():
    raw = pd.DataFrame(dict(OILPRODM3=[1e6, None], GASPIPVOL=[2e6, 0],
                            GCONDVOL=[1e5, 0], WATPRODVOL=[3e6, None]))
    result = ukcs.converted_volumes(raw)
    assert result.loc[0, "prfPrdOilNetMillSm3"] == 1
    assert result.loc[0, "prfPrdGasNetBillSm3"] == 2
    assert result.loc[0, "prfPrdOeNetMillSm3"] == 3.1
    assert result["prfPrdNGLNetMillSm3"].isna().all()
    assert pd.isna(result.loc[1, "prfPrdOeNetMillSm3"])


def test_pagination_uses_actual_page_size_and_rejects_errors():
    pages = [
        {"features": [{"attributes": {"OBJECTID": 1}}], "exceededTransferLimit": True},
        {"features": [{"attributes": {"OBJECTID": 2}}]},
    ]
    with patch("utils.ukcs.urlopen", side_effect=[BytesIO(json.dumps(page).encode()) for page in pages]) as get:
        assert len(ukcs.query(ukcs.FIELDS)) == 2
        query = parse_qs(urlparse(get.call_args.args[0]).query)
        assert query["resultOffset"] == ["1"]
    with patch("utils.ukcs.urlopen", return_value=BytesIO(b'{"error":{"code":400}}')):
        try:
            ukcs.query(ukcs.FIELDS)
            assert False, "Expected explicit service failure"
        except DataUnavailable:
            pass


def test_annual_reporting_rejects_duplicate_missing_cancellation_and_interior_partial():
    rows = []
    for year, first, last, months in (
        (2020, 9, 12, 4), (2021, 1, 12, 12), (2022, 1, 12, 12),
        (2023, 1, 11, 11), (2024, 1, 12, 12), (2025, 1, 7, 7),
    ):
        row = dict(FIELDNAME="TEST UK", PERIODYR=year, first_month=first, last_month=last, months=months)
        for column in ukcs.VOLUMES:
            row[column], row["n_" + column] = 1e6, months
        rows.append(row)
    rows[-2]["n_WATPRODVOL"] = 11
    duplicates = pd.DataFrame([dict(FIELDNAME="TEST UK", PERIODYR=2022, PERIODMNTH=3, records=2)])
    result = ukcs.prepare_annual(pd.DataFrame(rows), duplicates).set_index("prfYear")
    assert result.loc[2020, "partial_boundary_year"]
    assert result.loc[2025, "partial_boundary_year"]
    assert result.loc[2021, "complete_reporting"]
    for year in (2022, 2023):
        assert not result.loc[year, "complete_reporting"]
        assert result.loc[year, list(ukcs.YEARLY_COLUMNS)].isna().all()
    assert result.loc[2024, "complete_reporting"]
    assert pd.isna(result.loc[2024, "prfPrdProducedWaterInFieldMillSm3"])
    assert result.loc[2024, "prfPrdOilNetMillSm3"] == 1


def test_monthly_duplicate_reports_rejected():
    original = ukcs.load_monthly.__wrapped__
    features = [dict(attributes=dict(FIELDNAME="SAME", PERIODYR=2024, PERIODMNTH=1))] * 2
    with patch.object(ukcs, "query", return_value=features), pytest.raises(DataUnavailable, match="Multiple NSTA"):
        original("SAME")


def test_country_identity_and_unknown_denominators():
    tables = datasets()
    ncs = bm.build_master(tables["overview"], tables["reserves"], tables["inplace"],
                          tables["yearly"], tables["wells"], pd.DataFrame(), current_year=2025)
    master, yearly, wells = ukcs.namespace_ncs(ncs, tables["yearly"], tables["wells"])
    fields = ukcs.load_fields()
    fields = fields.assign(fldName="UKCS::OSEBERG", field_name="OSEBERG")
    uk_yearly = ukcs.load_yearly().assign(prfInformationCarrier="UKCS::OSEBERG")
    uk = ukcs.build_master(fields, uk_yearly, 2025)
    combined = pd.concat([master, uk])
    years = pd.concat([yearly, uk_yearly])
    assert combined.index.is_unique
    assert set(combined["country"]) == {"NCS", "UKCS"}
    assert uk["recoverable_oe"].isna().all()
    assert uk["producers_drilled"].isna().all()
    absolute = bm.normalised_profiles(years, combined, "oil", "absolute", wells=wells, current_year=2025)
    assert {"NCS::OSEBERG", "UKCS::OSEBERG"}.issubset(set(absolute["fldName"]))
    per_well = bm.normalised_profiles(years, combined, "oil", "per_well", wells=wells, current_year=2025)
    assert not per_well["fldName"].str.startswith("UKCS::").any()
    reserves = bm.normalised_profiles(years, combined, "oil", "pct_recoverable", current_year=2025)
    assert not reserves["fldName"].str.startswith("UKCS::").any()


def test_missing_profile_and_ratio_years_remain_chart_gaps():
    master = pd.DataFrame(dict(country=["UKCS"], hc_type=["OIL"]), index=["UKCS::TEST"])
    profiles = pd.DataFrame(dict(fldName=["UKCS::TEST"] * 2, year=[2020, 2022],
                                 years_on=[1, 3], value=[1., 0.5], gor=[100., 200.]))
    profile = figures.profile_figure(profiles, pd.DataFrame(), master, "Country", "country")
    assert list(profile.data[0].x) == [1, 2, 3]
    assert pd.isna(profile.data[0].y[1])
    assert "Test · UKCS" in profile.data[0].hovertemplate
    ratio = figures.ratio_figure(profiles, "gor", master, "Country", "country")
    assert pd.isna(ratio.data[0].y[1])


def test_database_switch_and_combined_country_filter():
    tables = datasets()
    monthly = tables["monthly"].copy()
    monthly["prfInformationCarrier"] = "UKCS::TEST UK"
    with (patch("utils.data.load_dataset", side_effect=lambda name: tables[name]),
          patch.object(ukcs, "load_monthly", return_value=monthly),
          patch.object(ukcs, "load_wells", return_value=pd.DataFrame()),
          patch.object(ukcs, "load_geometry", return_value=dict(lines=[[[60, 1], [60, 2], [61, 2], [60, 1]]],
                                                               points=[], outline_area_km2=20))):
        app = AppTest.from_file(str(ROOT / "app.py")).run()
        app.sidebar.segmented_control(key="workspace").set_value("Benchmark").run()
        assert not app.exception
        assert app.multiselect(key="bm_countries").value == ["NCS", "UKCS"]
        assert app.selectbox(key="bm_basis").value == "Annual volume"
        app.multiselect(key="bm_countries").set_value(["UKCS"]).run()
        assert not app.exception
        assert any("UKCS::TEST UK" in str(frame.value) for frame in app.dataframe)
        app.sidebar.segmented_control(key="database").set_value("UKCS · NSTA").run()
        assert not app.exception
        assert app.sidebar.selectbox(key="field").value == "UKCS::TEST UK"
        app.sidebar.segmented_control(key="workspace").set_value("Field Explorer").run()
        for section in ("Overview", "Production", "Wells & reservoir", "Map", "Economics", "Data & QA"):
            app.sidebar.radio[0].set_value(section).run()
            assert not app.exception, (section, app.exception)
            assert not app.error, (section, [message.value for message in app.error])
        app.sidebar.radio[0].set_value("Economics").run()
        assert any("not available for UKCS" in message.value for message in app.info)
        app.sidebar.segmented_control(key="database").set_value("NCS · SODIR").run()
        assert not app.exception


def test_uk_failure_is_visible_and_ncs_only_bypasses_uk_service():
    tables = datasets()
    with patch("utils.data.load_dataset", side_effect=lambda name: tables[name]):
        app = AppTest.from_file(str(ROOT / "app.py")).run()
        with patch.object(ukcs, "load_fields", side_effect=DataUnavailable("NSTA test outage")) as uk:
            app.sidebar.segmented_control(key="workspace").set_value("Benchmark").run()
            assert not app.exception
            assert any("UKCS peers unavailable" in message.value for message in app.warning)
            uk.reset_mock()
            app.multiselect(key="bm_countries").set_value(["NCS"]).run()
            assert not app.exception
            uk.assert_not_called()
            app.multiselect(key="bm_countries").set_value(["UKCS"]).run()
            assert not app.exception
            assert any("Select at least one available country" in message.value for message in app.info)


def test_map_context_bounds_queries_and_safe_labels():
    geometry = dict(lines=[[[57.7, .8], [57.8, .9]]], points=[])
    bounds = ukcs.context_bounds(geometry, 50)
    assert bounds[0] < .85 < bounds[2]
    assert bounds[1] < 57.75 < bounds[3]
    with pytest.raises(ValueError):
        ukcs.context_bounds(geometry, 500)
    feature = dict(attributes={"PIPE_NAME": "</script><script>alert(1)</script>"},
                   geometry={"paths": [[[.8, 57.7], [.9, 57.8]]]})
    with patch.object(ukcs, "query", return_value=[feature]) as query:
        context = LOAD_MAP_CONTEXT("Pipelines", bounds)
        assert query.call_args.kwargs["returnCentroid"] == "false"
        assert query.call_args.kwargs["geometryType"] == "esriGeometryEnvelope"
        assert query.call_args.args[0].endswith("FeatureServer/1")
    document = map_document("TEST", geometry, {}, provider="NSTA", context=[context], context_bounds=bounds)
    assert "</script><script>alert(1)" not in document
    assert '"context_bounds":' in document
    assert "North Sea" in document
    assert "Platforms / facilities" not in context["title"]
    with patch.object(ukcs, "query", return_value=[dict(attributes={}, geometry=None)]):
        with pytest.raises(DataUnavailable, match="usable map geometry"):
            LOAD_MAP_CONTEXT("Pipelines", bounds)


def test_uk_map_context_controls_persist_and_layer_failure_is_explicit():
    geometry = dict(lines=[[[57.7, .8], [57.8, .9], [57.7, .8]]], points=[], outline_area_km2=20)
    tables = datasets()
    with (patch("utils.data.load_dataset", side_effect=lambda name: tables[name]),
          patch.object(ukcs, "load_monthly", return_value=tables["monthly"]),
          patch.object(ukcs, "load_geometry", return_value=geometry)):
        app = AppTest.from_file(str(ROOT / "app.py")).run()
        app.sidebar.segmented_control(key="database").set_value("UKCS · NSTA").run()
        app.sidebar.radio[0].set_value("Map").run()
        assert not app.exception
        assert len(app.multiselect(key="map_uk_layers").value) == 3
        app.selectbox(key="map_uk_radius").set_value(100).run()
        app.multiselect(key="map_uk_layers").set_value(["Nearby fields", "Wellbores"]).run()
        app.sidebar.radio[0].set_value("Overview").run()
        app.sidebar.radio[0].set_value("Map").run()
        assert app.selectbox(key="map_uk_radius").value == 100
        assert app.multiselect(key="map_uk_layers").value == ["Nearby fields", "Wellbores"]
        with patch.object(ukcs, "load_map_context", side_effect=DataUnavailable("Test layer outage")):
            app.run()
            assert not app.exception
            assert any("other map layers remain usable" in warning.value for warning in app.warning)
            assert len(app.get("iframe")) == 1
