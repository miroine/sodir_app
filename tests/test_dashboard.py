from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from utils import data
from utils.callbaks_figure import (
    callback_investments,
    callback_plot_gas,
    callback_plot_reserve,
    field_map_url,
    fig_plot_gas,
    fig_plot_oil,
    update_tail_production,
)


ROOT = Path(__file__).resolve().parents[1]


def datasets():
    overview = pd.DataFrame({
        "fldName": ["OSEBERG", "EMPTY"],
        "fldNpdidField": [43625, 999],
        "fldCurrentActivitySatus": ["Producing", "Discovery"],
        "fldHcType": ["OIL/GAS", "OIL"],
        "fldMainArea": ["North sea", "North sea"],
        "cmpLongName": ["Equinor Energy AS", None],
    })
    monthly = data.prepare_monthly(pd.DataFrame({
        "prfInformationCarrier": ["OSEBERG", "OSEBERG"],
        "prfYear": [2024, 2024], "prfMonth": [3, 2],
        "prfPrdOilNetMillSm3": [31.0, 29.0],
        "prfPrdGasNetBillSm3": [0.031, 0.029],
        "prfPrdNGLNetMillSm3": [0.0, 0.0],
        "prfPrdCondensateNetMillSm3": [0.0, 0.0],
        "prfPrdOeNetMillSm3": [31.031, 29.029],
        "prfPrdProducedWaterInFieldMillSm3": [0.0, 0.0],
    }))
    yearly = data.prepare_yearly(pd.DataFrame({
        "prfInformationCarrier": ["OSEBERG"] * 4,
        "prfYear": [2021, 2022, 2023, 2024],
        "prfPrdOilNetMillSm3": [5.0, 10.0, 8.0, 6.0],
        "prfPrdGasNetBillSm3": [1.0, 2.0, 2.0, 2.0],
        "prfPrdNGLNetMillSm3": [0.0] * 4,
        "prfPrdCondensateNetMillSm3": [0.0] * 4,
        "prfPrdOeNetMillSm3": [6.0, 12.0, 10.0, 8.0],
        "prfPrdProducedWaterInFieldMillSm3": [0.5, 2.0, 4.0, 6.0],
    }))
    wells = data.prepare_wells(pd.DataFrame({
        "wlbWellboreName": ["30/9-B-1 H", "30/9-B-2 H", "30/9-B-3 H", "30/9-B-4 H"],
        "wlbField": ["OSEBERG"] * 4,
        "wlbPurpose": ["PRODUCTION", "PRODUCTION", "INJECTION", "OBSERVATION"],
        "wlbStatus": ["PRODUCING", "PLUGGED", "INJECTING", "PLUGGED"],
        "wlbContent": ["OIL", "OIL", "WATER", "NOT APPLICABLE"],
        "wlbCompletionYear": [2021, 2021, 2022, 2020],
        "wlbPluggedDate": [None, "15.06.2023", None, "01.01.2021"],
        "wlbTotalDepth": [4000, 4200, 3900, 3000],
        "wlbFinalVerticalDepth": [2600, 2650, 2580, 2500],
        "wlbSubSea": ["YES", " NO", " NO", " NO"],
        "wlbMultilateral": ["NO", "YES", "NO", "NO"],
    }))
    inplace = pd.DataFrame({
        "fldName": ["OSEBERG"], "fldInplaceOil": [100.0],
        "fldInplaceFreeGas": [0.2], "fldInplaceAssGas": [0.1],
    })
    reserves = pd.DataFrame({
        "fldName": ["OSEBERG"], "fldRemainingOil": [10.0],
        "fldRecoverableOil": [70.0], "fldRemainingGas": [0.04],
        "fldRecoverableGas": [0.1], "fldRecoverableOE": [70.1], "fldRemainingOE": [10.04],
    })
    description = pd.DataFrame({
        "fldName": ["OSEBERG"] * 3,
        "fldDescriptionHeading": ["Development", "Reservoir", "Recovery strategy"],
        "fldDescriptionText": [
            "Oseberg is a field in the northern part of the North Sea. The water depth is 100 metres. "
            "Oseberg was discovered in 1979, and the plan for development and operation (PDO) was approved in 1984. "
            "The production started in 1988. A subsea template tied-back to Oseberg B.",
            "Oseberg produces oil and gas from sandstone of Middle Jurassic age in the Brent Group. The main reservoirs "
            "are in the Oseberg and Tarbert Formations. The reservoirs are at depths of 2300-2700 metres and have generally good quality.",
            "The Oseberg field is produced by pressure depletion, as well as pressure maintenance using gas and water injection.",
        ],
    })
    return dict(
        overview=overview, monthly=monthly, yearly=yearly, wells=wells, inplace=inplace, reserves=reserves,
        description=description, investments=pd.DataFrame(), tops=pd.DataFrame(),
    )


class CalculationTests(unittest.TestCase):
    def setUp(self):
        self.tables = datasets()

    def test_calendar_days_gas_units_and_numeric_table(self):
        rates = data.daily_production(self.tables["monthly"])
        self.assertEqual(rates.index[0], pd.Timestamp("2024-02-01"))
        self.assertEqual(rates["Oil [Sm³/d]"].tolist(), [1e6, 1e6])
        self.assertEqual(rates["Gas [million Sm³/d]"].tolist(), [1.0, 1.0])
        table = update_tail_production(self.tables["monthly"])
        self.assertEqual(table.index.tolist(), ["02.2024", "03.2024"])
        self.assertTrue(pd.api.types.is_numeric_dtype(table.iloc[:, 0]))

    def test_zero_water_cut_and_empty_charts(self):
        monthly = self.tables["monthly"].copy()
        monthly["prfPrdOilNetMillSm3"] = 0
        water_cut = fig_plot_oil(monthly).data[-1].y
        self.assertTrue(pd.isna(water_cut).all())
        fig_plot_oil(monthly.iloc[:0]).to_json()
        fig_plot_gas(monthly.iloc[:0]).to_json()

    def test_reserve_number_is_produced_not_produced_plus_remaining(self):
        tables = {key: self.tables[key] for key in ("reserves", "inplace")}
        tables["production"] = self.tables["monthly"]
        oil = callback_plot_reserve("OSEBERG", **tables)
        gas = callback_plot_gas("OSEBERG", **tables)
        self.assertEqual(oil.data[0].value, 60.0)
        self.assertAlmostEqual(gas.data[0].value, 0.06)
        self.assertAlmostEqual(gas.data[0].gauge.axis.range[1], 0.3)
        self.assertIsNone(callback_plot_reserve("EMPTY", **tables))

    def test_latest_estimate_and_invalid_map_ids(self):
        estimates = pd.DataFrame({
            "fldDateOffResEstDisplay": ["31.12.2024", "31.12.2023"],
            "fldRemainingOil": [10, 20],
        })
        self.assertEqual(data.latest_row(estimates)["fldRemainingOil"], 10)
        estimates["fldDateOffResEstDisplay"] = None
        estimates["fldDateOffResEst"] = ["2024-01-12", "2023-12-31"]
        self.assertEqual(data.latest_row(estimates)["fldRemainingOil"], 10)
        overview = self.tables["overview"]
        self.assertIn("npdid=43625", field_map_url("OSEBERG", overview))
        self.assertIn("npdid=999", field_map_url("EMPTY", overview))
        self.assertIsNone(field_map_url("UNKNOWN", overview))
        for value in ("<script>", 1.5, -1, None):
            invalid = overview.iloc[:1].copy()
            invalid["fldNpdidField"] = value
            self.assertIsNone(field_map_url("OSEBERG", invalid))
        self.assertIsNone(callback_investments("EMPTY", pd.DataFrame()))

    def test_loader_cache_timeout_and_recovery(self):
        data.load_dataset.clear()
        try:
            with patch("utils.data.urlopen", return_value=BytesIO(b"fldName\nOSEBERG\n")) as request:
                first = data.load_dataset("overview")
                first.loc[0, "fldName"] = "MUTATED"
                second = data.load_dataset("overview")
                self.assertEqual(second.loc[0, "fldName"], "OSEBERG")
                request.assert_called_once()
                self.assertEqual(request.call_args.kwargs["timeout"], 45)
            data.load_dataset.clear()
            with patch("utils.data.urlopen", side_effect=[
                TimeoutError(), BytesIO(b"fldName\nOSEBERG\n"),
            ]) as request:
                with self.assertRaises(data.DataUnavailable):
                    data.load_dataset("overview")
                self.assertFalse(data.load_dataset("overview").empty)
                self.assertEqual(request.call_count, 2)
            data.load_dataset.clear()
            with patch("utils.data.urlopen", return_value=BytesIO(b"<html>unavailable</html>")):
                with self.assertRaises(data.DataUnavailable):
                    data.load_dataset("overview")
        finally:
            data.load_dataset.clear()

    def test_mixed_estimate_dates_and_nonfinite_values(self):
        estimates = pd.DataFrame({
            "fldDateOffResEstDisplay": ["2024-01-12", "31.12.2023", None],
            "fldRemainingOil": [10, 20, 30],
        })
        self.assertEqual(data.latest_row(estimates)["fldRemainingOil"], 10)
        for value in ("inf", "-inf", "not numeric", None):
            self.assertIsNone(data.number(pd.Series({"volume": value}), "volume"))
        monthly = self.tables["monthly"].copy()
        monthly["prfPrdOilNetMillSm3"] = float("inf")
        self.assertTrue(data.daily_production(monthly)["Oil [Sm³/d]"].isna().all())


class DashboardTests(unittest.TestCase):
    def test_retained_upload_survives_navigation_can_be_cleared_and_resets_with_field(self):
        tables = datasets()
        profile = BytesIO(b"year,oil\n1,1.0\n2,0.8\n")
        profile.name = "profile.csv"
        with patch("utils.data.load_dataset", side_effect=lambda name: tables[name]):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            app.session_state["saved_uploads"] = {"bm_upload": profile}
            app.sidebar.segmented_control(key="workspace").set_value("Benchmark").run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("Retained for this field: profile.csv" in item.value for item in app.caption))
            app.sidebar.segmented_control(key="workspace").set_value("Field Explorer").run()
            app.run()
            app.sidebar.segmented_control(key="workspace").set_value("Benchmark").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.session_state["saved_uploads"]["bm_upload"].getvalue(), profile.getvalue())
            app.button(key="bm_upload_clear").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertNotIn("bm_upload", app.session_state["saved_uploads"])
            app.session_state["saved_uploads"] = {"bm_upload": profile}
            app.sidebar.selectbox[0].select("EMPTY").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.session_state["saved_uploads"], {})

    def test_benchmark_parameters_survive_navigation_and_reset_on_field_change(self):
        tables = datasets()
        with patch("utils.data.load_dataset", side_effect=lambda name: tables[name]):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            app.sidebar.segmented_control(key="workspace").set_value("Benchmark").run()
            app.selectbox(key="bm_basis").select("Per producing well").run()
            app.multiselect(key="bm_fm").select("Tarbert").run()
            app.number_input(key="bm_minyears").set_value(0).run()
            app.sidebar.segmented_control(key="workspace").set_value("Field Explorer").run()
            app.run()
            app.sidebar.segmented_control(key="workspace").set_value("Benchmark").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.selectbox(key="bm_basis").value, "Per producing well")
            self.assertEqual(app.multiselect(key="bm_fm").value, ["Tarbert"])
            self.assertEqual(app.number_input(key="bm_minyears").value, 0)
            app.sidebar.segmented_control(key="workspace").set_value("Field Explorer").run()
            app.sidebar.selectbox[0].select("EMPTY").run()
            app.sidebar.segmented_control(key="workspace").set_value("Benchmark").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.multiselect(key="bm_fm").value, [])
            self.assertEqual(app.number_input(key="bm_minyears").value, 3)

    def test_missing_development_tops_offer_explicit_discovery_well_option(self):
        tables = datasets()
        tables["overview"]["wlbName"] = ["30/9-1", None]
        tables["tops"] = pd.DataFrame({
            "wlbName": ["30/9-1", "99/1-1"],
            "lsuName": ["TARBERT FM", "UNRELATED FM"],
            "lsuTopDepth": [2600, 1000],
            "lsuBottomDepth": [2700, 1200],
        })
        with patch("utils.data.load_dataset", side_effect=lambda name: tables[name]):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            app.sidebar.radio[0].set_value("Wells & reservoir").run()
            app.checkbox[0].check().run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("no formation tops" in item.value for item in app.info))
            self.assertEqual(len(app.dataframe), 2)
            app.checkbox[1].check().run()
            self.assertEqual(len(app.exception), 0)
            summary = app.dataframe[-1].value
            self.assertEqual(summary.index.tolist(), ["TARBERT FM"])
            self.assertEqual(summary.loc["TARBERT FM", "thickness_median"], 100)
            self.assertTrue(any("not a development well" in item.value for item in app.caption))

    def test_development_tops_without_extracted_match_show_all_units_and_thickness(self):
        tables = datasets()
        tables["tops"] = pd.DataFrame({
            "wlbName": ["30/9-B-1 H"],
            "lsuName": ["OTHER FM"],
            "lsuTopDepth": [2000],
            "lsuBottomDepth": [2100],
        })
        with patch("utils.data.load_dataset", side_effect=lambda name: tables[name]):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            app.sidebar.radio[0].set_value("Wells & reservoir").run()
            app.checkbox[0].check().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.dataframe[-1].value.loc["OTHER FM", "thickness_median"], 100)
            self.assertEqual(len(app.checkbox), 1)

    def test_themes_period_filter_and_single_month(self):
        tables = datasets()
        with patch("utils.data.load_dataset", side_effect=lambda name: tables[name]):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            app.sidebar.selectbox[1].select("Dark").run()
            app.sidebar.radio[0].set_value("Production").run()
            self.assertEqual(len(app.exception), 0)
            month = tables["monthly"].index[0]
            app.select_slider[0].set_value((month, month)).run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.dataframe[0].value), 1)
            app.sidebar.selectbox[1].select("Light").run()
            self.assertEqual(len(app.exception), 0)
        tables["monthly"] = tables["monthly"].iloc[:1]
        with patch("utils.data.load_dataset", side_effect=lambda name: tables[name]):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            app.sidebar.radio[0].set_value("Production").run()
            self.assertEqual(len(app.exception), 0)

    def test_outage_reuses_timestamped_data_and_limits_retries(self):
        tables = datasets()
        tables["overview"].attrs["fetched_at"] = datetime(2024, 1, 1, tzinfo=timezone.utc)
        with patch("utils.data.load_dataset", side_effect=lambda name: tables[name]) as loader:
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            loader.side_effect = data.DataUnavailable("Service unavailable")
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("2024-01-01" in warning.value for warning in app.warning))
            self.assertEqual(app.title[0].value, "Oseberg")
            count = loader.call_count
            app.run()
            self.assertEqual(loader.call_count, count)
            app.sidebar.button[0].click().run()
            self.assertGreater(loader.call_count, count)
            self.assertEqual(len(app.exception), 0)

    def test_overview_shows_extracted_facts_and_descriptions(self):
        tables = datasets()
        with patch("utils.data.load_dataset", side_effect=lambda name: tables[name]):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.title[0].value, "Oseberg")
            html = " ".join(block.value for block in app.markdown)
            self.assertIn("Water &amp; gas injection", html)
            self.assertIn("Tarbert", html)
            self.assertIn("2,300–2,700 m", html)
            self.assertIn("2 drilled · 1 active", html)
            self.assertIn("oil 70%", html)
            self.assertEqual(len(app.expander), 0)
            self.assertIn("description-card", html)
            app.sidebar.selectbox[0].select("EMPTY").run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(all(metric.value == "—" for metric in app.metric))

    def test_sections_switching_and_missing_data(self):
        tables = datasets()
        with patch("utils.data.load_dataset", side_effect=lambda name: tables[name]) as loader:
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            self.assertEqual(len(app.exception), 0)
            self.assertNotIn("tops", [call.args[0] for call in loader.call_args_list])
            app.sidebar.selectbox[0].select("EMPTY").run()
            for section in ("Production", "Reserves", "Investments", "Wells & reservoir"):
                app.sidebar.radio[0].set_value(section).run()
                self.assertEqual(len(app.exception), 0, section)
                self.assertGreater(len(app.info), 0, section)
            app.sidebar.selectbox[0].select("OSEBERG").run()
            app.sidebar.radio[0].set_value("Production").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.get("plotly_chart")), 5)
            app.sidebar.radio[0].set_value("Reserves").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.get("plotly_chart")), 2)
            app.sidebar.radio[0].set_value("Wells & reservoir").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.metric[0].value, "2")
            self.assertEqual(app.metric[1].value, "1")
            self.assertEqual(len(app.dataframe), 2)
            app.sidebar.radio[0].set_value("Data & QA").run()
            self.assertEqual(len(app.exception), 0)

    def test_benchmark_section_renders_all_tabs_and_filters(self):
        tables = datasets()
        with patch("utils.data.load_dataset", side_effect=lambda name: tables[name]):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            app.sidebar.segmented_control(key="workspace").set_value("Benchmark").run()
            self.assertEqual(len(app.exception), 0)
            self.assertGreaterEqual(len(app.get("plotly_chart")), 10)
            app.number_input(key="bm_minyears").set_value(0).run()
            for basis in ("Annual volume", "Per producing well", "% of in-place volume"):
                app.selectbox(key="bm_basis").select(basis).run()
                self.assertEqual(len(app.exception), 0, basis)
            app.selectbox(key="bm_color").select("Main formation").run()
            app.multiselect(key="bm_fm").select("Tarbert").run()
            self.assertEqual(len(app.exception), 0)
            lede = " ".join(block.value for block in app.markdown)
            self.assertIn("1 peer fields", lede)
            app.multiselect(key="bm_hc").select("OIL").run()
            self.assertEqual(len(app.exception), 0)
            self.assertIn("No fields match", " ".join(block.value for block in app.markdown))

    def test_service_failure_is_visible(self):
        with patch("utils.data.load_dataset", side_effect=data.DataUnavailable("Service unavailable")):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.error[0].value, "Service unavailable")

    def test_missing_production_does_not_disable_overview(self):
        tables = datasets()

        def load(name):
            if name == "monthly":
                raise data.DataUnavailable("Production unavailable")
            return tables[name]

        with patch("utils.data.load_dataset", side_effect=load):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.warning[0].value, "Production unavailable")
            self.assertTrue(all(metric.value == "—" for metric in app.metric))
            self.assertIn("2 drilled · 1 active", " ".join(block.value for block in app.markdown))


if __name__ == "__main__":
    unittest.main()
