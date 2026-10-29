import unittest
from io import BytesIO
from unittest.mock import patch

import pandas as pd
import numpy as np
from streamlit.testing.v1 import AppTest

from utils import economics as econ
from test_dashboard import ROOT, datasets


class EconomicsTests(unittest.TestCase):
    def test_product_decline_is_fitted_and_capex_uses_available_five_year_window(self):
        production = pd.DataFrame({
            "year": range(2020, 2025), "oil": 10 * 0.8 ** np.arange(5),
            "gas": 2 * 0.9 ** np.arange(5),
        })
        forecast, fits = econ.fitted_forecast(production, 2024, 3)
        np.testing.assert_allclose(forecast["oil"], 10 * 0.8 ** np.arange(5, 8))
        np.testing.assert_allclose(forecast["gas"], 2 * 0.9 ** np.arange(5, 8))
        self.assertAlmostEqual(fits.set_index("product").loc["oil", "effective_decline_pct"], 20)
        self.assertAlmostEqual(fits.set_index("product").loc["gas", "r_squared"], 1)
        # A future point must never leak into the fit.
        with_future = pd.concat([production, pd.DataFrame({"year": [2025], "oil": [100], "gas": [50]})])
        pd.testing.assert_frame_equal(econ.fitted_forecast(with_future, 2024, 3)[0], forecast)
        for invalid in (
            pd.DataFrame({"year": range(2020, 2025), "oil": [1, 2, 3, 4, 5]}),
            pd.DataFrame({"year": [2023, 2024], "oil": [2, 1]}),
            pd.DataFrame({"year": [2022, 2023, 2024], "oil": [2, 0, 1]}),
        ):
            with self.assertRaises(ValueError):
                econ.fitted_forecast(invalid, 2024, 3)
        costs = pd.DataFrame({"year": [2019, 2020, 2022, 2023, 2024, 2025],
                              "nominal_mnok": [9999, 100, 0, -20, 200, 9999]})
        mean, window, missing = econ.recent_investment_average(costs, 2024)
        self.assertEqual(mean, 70)
        self.assertEqual(window["year"].tolist(), [2020, 2022, 2023, 2024])
        self.assertEqual(missing, [2021])

    def test_tax_depreciation_loss_offsets_and_next_year_refund(self):
        data = pd.DataFrame({"year": [2020, 2021], "investment_mnok": [600.0, 0],
                             "operating_margin_mnok": [0.0, 300],
                             "free_cash_flow_mnok": [-600.0, 300], "basis": ["History", "Forecast"]})
        result = econ.current_regime_tax(data, econ.TaxAssumptions(50))
        self.assertEqual(result["ordinary_depreciation_mnok"].tolist(), [100] * 6 + [0, 0])
        self.assertEqual(result.loc[0, "ordinary_loss_closing_mnok"], 150)
        self.assertEqual(result.loc[1, "ordinary_tax_mnok"], 11)
        self.assertEqual(result.loc[0, "special_refund_received_mnok"], 0)
        self.assertAlmostEqual(result.loc[1, "special_refund_received_mnok"], 600 * 0.718)
        self.assertAlmostEqual(result.loc[1, "special_tax_assessed_mnok"], (300 - 11) * 0.718)
        self.assertAlmostEqual(result.loc[1, "after_tax_cash_flow_mnok"], 300 - 11 - 289 * 0.718 + 600 * 0.718)
        self.assertEqual(result.loc[6, "ordinary_depreciation_mnok"], 0)
        self.assertEqual(result.loc[0, "calculated_negative_tax_closing_mnok"], 33)
        self.assertEqual(result.loc[1, "calculated_ordinary_tax_mnok"], 11)

    def test_irr_and_valuation_periods(self):
        irr, _ = econ.cash_flow_irr([-100, 60, 60])
        self.assertAlmostEqual(irr, 0.1306623863)
        self.assertIsNone(econ.cash_flow_irr([10, 20])[0])
        self.assertIsNone(econ.cash_flow_irr([-100, 230, -132])[0])
        frame = pd.DataFrame({"year": [2020, 2021, 2022],
                              "free_cash_flow_mnok": [-100, 60, 60],
                              "after_tax_cash_flow_mnok": [-100, 50, 50]})
        full = econ.valuation(frame, 0.1)
        forward = econ.valuation(frame, 0.1, 2020)
        self.assertAlmostEqual(full["after_tax_npv_mnok"], -100 / 1.1 + 50 / 1.1**2 + 50 / 1.1**3)
        self.assertAlmostEqual(forward["after_tax_npv_mnok"], 50 / 1.1 + 50 / 1.1**2)
        self.assertIsNone(forward["irr"])

    def test_after_tax_break_even_and_forward_sunk_costs(self):
        assumptions = econ.Assumptions(10, 0, 0, 0, 1, 0, 0, 0)
        history = pd.DataFrame({"year": [2020], "oil": [0.0], "investment_mnok": [100.0]})
        forecast = pd.DataFrame({"year": [2021, 2022], "oil": [1.0, 1.0], "investment_mnok": [10.0, 10.0]})
        result, summary = econ.evaluate(history, forecast, assumptions, econ.TaxAssumptions())
        price = summary["full_valuation"]["break_even_oil_usd_bbl"]
        self.assertIsNotNone(price)
        check, root = econ.evaluate(history, forecast, econ.Assumptions(price, 0, 0, 0, 1, 0, 0, 0), econ.TaxAssumptions())
        self.assertAlmostEqual(root["full_valuation"]["after_tax_npv_mnok"], 0, places=6)
        # Forward carries the refund due from pre-cutoff investment, not the sunk outflow.
        expected = result.loc[result["year"] > 2020, "after_tax_cash_flow_mnok"].sum()
        self.assertAlmostEqual(summary["forward_valuation"]["after_tax_npv_mnok"], expected)
        self.assertEqual(summary["forward_valuation"]["break_even_oil_usd_bbl"], None)
        self.assertIn("zero oil price", summary["forward_valuation"]["break_even_status"])
        self.assertEqual(result["basis"].iloc[-1], "Tax settlement only")
        self.assertEqual(result["cumulative_cash_flow_mnok"].iloc[-1],
                         result["cumulative_cash_flow_mnok"].iloc[-7])

    def test_forward_break_even_reprices_only_future_and_ignores_no_oil(self):
        a = econ.Assumptions(10, 0.1, 0, 0, 1, 0, 0, 0.08)
        history = pd.DataFrame({"year": [2020], "oil": [1.0], "gas": [0.0], "investment_mnok": [1.0]})
        forecast = pd.DataFrame({"year": [2021, 2022], "oil": [1.0, 0.8], "gas": [0.01, 0.01],
                                 "investment_mnok": [100.0, 100.0]})
        result, summary = econ.evaluate(history, forecast, a, econ.TaxAssumptions())
        price = summary["forward_valuation"]["break_even_oil_usd_bbl"]
        self.assertIsNotNone(price)
        scenario = result.loc[result["basis"].ne("Tax settlement only")].copy()
        future = scenario["year"].gt(2020)
        change = scenario.loc[future, "oil"] * 6.28981 * (price - 10)
        for column in ("revenue_mnok", "operating_margin_mnok", "free_cash_flow_mnok"):
            scenario.loc[future, column] += change
        ledger = econ.current_regime_tax(scenario, econ.TaxAssumptions())
        self.assertAlmostEqual(econ.valuation(ledger, 0.08, 2020)["after_tax_npv_mnok"], 0, places=6)
        self.assertEqual(ledger.loc[0, "tax_cash_mnok"], result.loc[0, "tax_cash_mnok"])
        forecast["oil"] = 0.0
        _, summary = econ.evaluate(history, forecast, a, econ.TaxAssumptions())
        self.assertIsNone(summary["forward_valuation"]["break_even_oil_usd_bbl"])
        self.assertIn("No oil", summary["forward_valuation"]["break_even_status"])

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
            app.radio(key="econ_mode").set_value("History-fitted decline").run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("rising" in item.value for item in app.error))
            # Replace ramp-up history with a genuine declining tail.
            tables["yearly"]["prfPrdOilNetMillSm3"] = [10, 8, 6.4, 5.12]
            tables["yearly"]["prfPrdGasNetBillSm3"] = [2, 1.8, 1.62, 1.458]
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.dataframe[-1].value), 41)
            self.assertTrue(any("After-tax NPV" in metric.label for metric in app.metric))
            app.sidebar.radio[0].set_value("Overview").run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("Last calculated scenario" in item.value for item in app.markdown))


if __name__ == "__main__":
    unittest.main()
