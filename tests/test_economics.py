import unittest
from io import BytesIO
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from utils import economics as econ
from test_dashboard import ROOT, datasets


class EconomicsTests(unittest.TestCase):
    def test_excel_prognosis_round_trip(self):
        source = pd.DataFrame({"year": [2030, 2031], "gas": [1.0, 0.8], "investment_mnok": [100, 50]})
        output = BytesIO()
        source.to_excel(output, index=False)
        result = econ.parse_prognosis(output.getvalue(), "forecast.xlsx")
        self.assertEqual(result["gas"].tolist(), [1.0, 0.8])
        self.assertEqual(result["investment_mnok"].tolist(), [100, 50])
        self.assertEqual(result["oil"].tolist(), [0, 0])

    def test_product_units_opex_discounting_and_payback(self):
        history = pd.DataFrame({
            "year": [2020, 2021, 2022], "oil": [0.0, 1.0, 1.0],
            "gas": [0.0, 1.0, 0.0], "ngl": [0.0, 0.1, 0.0],
            "condensate": [0.0, 0.2, 0.0], "investment_mnok": [100.0, 0.0, 0.0],
        })
        assumptions = econ.Assumptions(10, 0.1, 20, 5, 1, 0, 0, 0.1)
        results, summary = econ.evaluate(history, pd.DataFrame(), assumptions)
        expected = (1 * 10 + 0.2 * 20 + 0.1 * 5) * 6.28981 + 100
        self.assertAlmostEqual(results.loc[1, "revenue_mnok"], expected)
        self.assertAlmostEqual(results.loc[1, "oe"], 2.39)
        self.assertEqual(summary["payback_year"], 2021)
        self.assertAlmostEqual(results.loc[0, "discounted_cash_flow_mnok"], -100 / 1.1)
        self.assertIsNone(summary["cessation_year"])
        self.assertIsNone(summary["economic_limit_year"])

    def test_decline_and_economic_limit_are_scenario_only(self):
        history = pd.DataFrame({"year": [2020], "oil": [1.0], "investment_mnok": [100.0]})
        forecast = econ.decline_forecast(history.iloc[0].to_dict(), 0.5, 3)
        self.assertEqual(forecast["oil"].tolist(), [0.5, 0.25, 0.125])
        forecast["investment_mnok"] = 0.0
        result, summary = econ.evaluate(history, forecast, econ.Assumptions(10, 0, 0, 0, 1, 0, 20, 0))
        self.assertEqual(summary["economic_limit_year"], 2022)
        self.assertEqual(summary["cessation_year"], 2021)
        self.assertIsNone(summary["payback_year"])
        self.assertEqual(len(result), 4)
        self.assertEqual(result["basis"].iloc[-1], "Forecast scenario")
        forecast["investment_mnok"] = 10000
        _, same_limit = econ.evaluate(history, forecast, econ.Assumptions(10, 0, 0, 0, 1, 0, 20, 0))
        self.assertEqual(same_limit["economic_limit_year"], 2022)

    def test_profile_validation_and_forecast_alignment(self):
        for content in (
            b"year,oil\n2030,-1\n", b"year,oil\n2030,inf\n", b"year,oil\n2030,\n",
            b"year,oil\n2030.5,1\n", b"year,oil\n2030,1\n2030,2\n",
            b"year,oil\n2030,1\n2032,2\n", b"year,oe\n2030,1\n",
            b"year,oil,investment_mnok\n2030,1,inf\n",
        ):
            with self.assertRaises(ValueError):
                econ.parse_prognosis(content, "forecast.csv")
        profile = econ.parse_prognosis(b"year,gas\n2030,1\n2031,0\n", "forecast.csv")
        self.assertEqual(profile["oil"].tolist(), [0, 0])
        history = pd.DataFrame({"year": [2020], "oil": [1], "investment_mnok": [1]})
        with self.assertRaisesRegex(ValueError, "immediately"):
            econ.evaluate(history, profile, econ.Assumptions())
        with self.assertRaisesRegex(ValueError, "Explicit investment"):
            econ.evaluate(history.drop(columns="investment_mnok"), pd.DataFrame(), econ.Assumptions())
        for assumptions in (econ.Assumptions(nok_per_usd=0), econ.Assumptions(gas_usd_sm3=-1),
                            econ.Assumptions(discount_rate=1.1), econ.Assumptions(oil_usd_bbl=float("inf"))):
            with self.assertRaises(ValueError):
                assumptions.validate()

    def test_history_does_not_invent_missing_costs_or_production(self):
        production = pd.DataFrame({"year": [2021, 2022], "oil": [1, 2]})
        investments = pd.DataFrame({"year": [2020, 2021, 2022], "nominal_mnok": [100, 50, 0]})
        history = econ.historical_profile(production, investments, 2022)
        self.assertEqual(history["oil"].tolist(), [0, 1, 2])
        self.assertEqual(history["investment_mnok"].tolist(), [100, 50, 0])
        with self.assertRaisesRegex(ValueError, "Investment years are missing"):
            econ.historical_profile(production, investments.loc[investments.year.ne(2021)], 2022)
        with self.assertRaisesRegex(ValueError, "does not extend"):
            econ.historical_profile(production, pd.DataFrame({"year": [2020, 2021, 2022, 2023], "nominal_mnok": [1, 1, 1, 1]}), 2023)

    def test_initial_zero_balance_is_not_called_payback(self):
        history = pd.DataFrame({"year": [2020, 2021], "oil": [0, 1], "investment_mnok": [0, 0]})
        _, summary = econ.evaluate(history, pd.DataFrame(), econ.Assumptions())
        self.assertIsNone(summary["payback_year"])

    def test_dashboard_requires_confirmation_and_preserves_scenario_context(self):
        tables = datasets()
        tables["investments"] = pd.DataFrame({
            "prfInformationCarrier": ["OSEBERG"] * 5,
            "prfYear": [2020, 2021, 2022, 2023, 2024],
            "prfInvestmentsMillNOK": [10000, 1000, 1000, 1000, 1000],
        })
        with patch("utils.data.load_dataset", side_effect=lambda name: tables[name]):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            app.sidebar.radio[0].set_value("Economics").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.metric), 0)
            app.checkbox(key="econ_confirm_OSEBERG").check().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.get("plotly_chart")), 2)
            self.assertTrue(any("cessation cannot be estimated" in item.value for item in app.info))
            app.radio(key="econ_mode").set_value("Illustrative decline scenario").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.dataframe[-1].value), 35)
            app.sidebar.radio[0].set_value("Overview").run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("Last calculated scenario" in item.value for item in app.markdown))


if __name__ == "__main__":
    unittest.main()
