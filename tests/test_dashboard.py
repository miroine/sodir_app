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
    inplace = pd.DataFrame({
        "fldName": ["OSEBERG"], "fldInplaceOil": [100.0],
        "fldInplaceFreeGas": [0.2], "fldInplaceAssGas": [0.1],
    })
    reserves = pd.DataFrame({
        "fldName": ["OSEBERG"], "fldRemainingOil": [10.0],
        "fldRecoverableOil": [70.0], "fldRemainingGas": [0.04],
        "fldRecoverableGas": [0.1],
    })
    return dict(
        overview=overview, monthly=monthly, inplace=inplace, reserves=reserves,
        description=pd.DataFrame({
            "fldName": ["OSEBERG"], "fldDescriptionHeading": [None],
            "fldDescriptionText": [None],
        }),
        investments=pd.DataFrame(),
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
                self.assertEqual(request.call_args.kwargs["timeout"], 20)
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
    def test_themes_period_filter_and_single_month(self):
        tables = datasets()
        with patch("utils.data.load_dataset", side_effect=lambda name: tables[name]):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            app.sidebar.selectbox[2].select("Dark").run()
            app.sidebar.radio[0].set_value("Production").run()
            self.assertEqual(len(app.exception), 0)
            month = tables["monthly"].index[0]
            app.select_slider[0].set_value((month, month)).run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.dataframe[0].value), 1)
            app.sidebar.selectbox[2].select("Light").run()
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
            self.assertEqual(app.title[0].value, "OSEBERG")
            count = loader.call_count
            app.run()
            self.assertEqual(loader.call_count, count)
            app.sidebar.button[0].click().run()
            self.assertGreater(loader.call_count, count)
            self.assertEqual(len(app.exception), 0)

    def test_sections_switching_missing_data_and_lazy_loading(self):
        tables = datasets()
        with patch("utils.data.load_dataset", side_effect=lambda name: tables[name]) as loader:
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.title[0].value, "OSEBERG")
            self.assertNotIn("description", [call.args[0] for call in loader.call_args_list])
            self.assertNotIn("reserves", [call.args[0] for call in loader.call_args_list])
            frames = app.get("iframe")
            self.assertIn("npdid=43625", frames[0].proto.src)
            app.sidebar.selectbox[1].select("EMPTY").run()
            self.assertEqual(len(app.exception), 0)
            self.assertIn("npdid=999", app.get("iframe")[0].proto.src)
            self.assertTrue(all(metric.value == "—" for metric in app.metric))
            for section in ("Production", "Reserves", "Investments"):
                app.sidebar.radio[0].set_value(section).run()
                self.assertEqual(len(app.exception), 0)
                self.assertGreater(len(app.info), 0)
            app.sidebar.selectbox[1].select("OSEBERG").run()
            for section in ("Production", "Reserves"):
                app.sidebar.radio[0].set_value(section).run()
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(len(app.get("plotly_chart")), 2)
            app.sidebar.radio[0].set_value("Overview").run()
            app.checkbox[0].check().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.expander), 5)

    def test_service_failure_is_visible(self):
        with patch("utils.data.load_dataset", side_effect=data.DataUnavailable("Service unavailable")):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.error[0].value, "Service unavailable")

    def test_missing_production_does_not_disable_map(self):
        tables = datasets()

        def load(name):
            if name == "monthly":
                raise data.DataUnavailable("Production unavailable")
            return tables[name]

        with patch("utils.data.load_dataset", side_effect=load):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.warning[0].value, "Production unavailable")
            self.assertIn("npdid=43625", app.get("iframe")[0].proto.src)
            self.assertTrue(all(metric.value == "—" for metric in app.metric))


if __name__ == "__main__":
    unittest.main()
