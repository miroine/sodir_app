import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from utils import figures, investments as inv
from test_benchmark import master_tables
from test_dashboard import ROOT, datasets


def investment_data():
    return pd.DataFrame({
        "prfInformationCarrier": ["OSEBERG"] * 6,
        "prfYear": [2020, 2021, 2022, 2023, 2024, 2025],
        "prfInvestmentsMillNOK": [100, 200, 300, -10, 0, 999],
    })


class InvestmentTests(unittest.TestCase):
    def test_metrics_use_correct_barrel_conversion_and_cutoff(self):
        master, tables = master_tables()
        annual = inv.adjusted_investments(inv.prepare_investments(investment_data(), 2025))
        summary, history = inv.benchmark_tables(annual, master, tables["yearly"], tables["wells"], 2022)
        row = summary.loc["OSEBERG"]
        self.assertEqual(row["investment_million"], 600)
        self.assertEqual(row["investment_first_year"], 2020)
        self.assertEqual(row["investment_years"], 3)
        self.assertEqual(row["development_wells_through_cutoff"], 4)
        self.assertEqual(row["producers_through_cutoff"], 2)
        self.assertEqual(row["per_development_well_million"], 150)
        self.assertEqual(row["per_producer_million"], 300)
        self.assertAlmostEqual(row["per_produced_boe"], 600 / (18 * inv.BOE_PER_SM3))
        self.assertAlmostEqual(row["per_recoverable_boe"], 600 / (70.1 * inv.BOE_PER_SM3))
        self.assertEqual(history["cumulative_million"].tolist(), [100, 300, 600])
        self.assertTrue(pd.isna(history.iloc[0]["per_annual_boe"]))
        self.assertAlmostEqual(history.iloc[2]["per_annual_boe"], 300 / (12 * inv.BOE_PER_SM3))
        self.assertTrue(pd.isna(summary.loc["EMPTY", "investment_million"]))

    def test_user_inflation_and_fx_are_applied_per_year_before_summing(self):
        data = inv.prepare_investments(investment_data(), 2025)
        index = inv.parse_price_index(b"year,index\n2020,50\n2021,100\n2022,125\n2023,200\n2024,200\n")
        adjusted = inv.adjusted_investments(data, nok_per_unit=10, price_index=index, base_year=2024)
        self.assertEqual(adjusted["inflation_factor"].tolist(), [4, 2, 1.6, 1, 1])
        self.assertEqual(adjusted["investment_million"].tolist(), [40, 40, 48, -1, 0])
        self.assertEqual(adjusted["nominal_mnok"].tolist(), [100, 200, 300, -10, 0])
        for rate in (0, -1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                inv.adjusted_investments(data, rate)
        with self.assertRaisesRegex(ValueError, "missing investment years"):
            inv.adjusted_investments(data, price_index=index.drop(2021), base_year=2024)
        with self.assertRaisesRegex(ValueError, "reference year"):
            inv.adjusted_investments(data, price_index=index, base_year=2025)

    def test_invalid_price_indices_and_investments_fail_explicitly(self):
        for content in (
            b"year,index\n2020,0\n", b"year,index\n2020,-1\n",
            b"year,index\n2020,inf\n", b"year,index\n2020,\n",
            b"year,index\n2020,100\n2020,101\n", b"year,index\n2020.5,100\n",
            b"year,value\n2020,100\n", b"year,index\ninf,100\n",
        ):
            with self.assertRaises(ValueError):
                inv.parse_price_index(content)
        bad = investment_data()
        bad["prfInvestmentsMillNOK"] = bad["prfInvestmentsMillNOK"].astype(object)
        bad.loc[0, "prfInvestmentsMillNOK"] = "invalid"
        with self.assertRaises(ValueError):
            inv.prepare_investments(bad, 2025)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            inv.prepare_investments(pd.concat([investment_data()] * 2), 2025)

    def test_missing_years_and_zero_denominators_are_not_filled(self):
        master, tables = master_tables()
        master["recoverable_oe"] = 0
        annual = inv.adjusted_investments(inv.prepare_investments(investment_data(), 2025))
        annual = annual.loc[annual["year"].ne(2021)]
        summary, history = inv.benchmark_tables(annual, master, tables["yearly"], tables["wells"].iloc[:0], 2023)
        self.assertEqual(summary.loc["OSEBERG", "investment_million"], 390)
        self.assertEqual(summary.loc["OSEBERG", "missing_investment_years"], 1)
        self.assertTrue(summary["per_recoverable_boe"].isna().all())
        self.assertTrue(summary["per_producer_million"].isna().all())
        fig = figures.investment_history(history, master, "investment_million", "Annual", "NOK",
                                         "HC type", "hc_type")
        self.assertEqual(list(fig.data[0].x), [2020, 2021, 2022, 2023])
        self.assertTrue(pd.isna(fig.data[0].y[1]))
        self.assertFalse(fig.data[0].connectgaps)
        figures.investment_ranking(master.join(summary), "investment_million", "Investment", "NOK",
                                   "HC type", "hc_type", highlight="OSEBERG", dark=True).to_json()

    def test_dashboard_cost_metrics_currency_filters_and_inflation_gate(self):
        tables = datasets()
        tables["investments"] = investment_data()
        with patch("utils.data.load_dataset", side_effect=lambda name: tables[name]):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            app.sidebar.segmented_control(key="workspace").set_value("Benchmark").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.selectbox(key="cost_cutoff").value, 2025)
            app.selectbox(key="cost_metric").select("Investment / produced boe").run()
            app.selectbox(key="cost_currency").select("USD").run()
            app.number_input(key="cost_fx_USD").set_value(10).run()
            self.assertEqual(len(app.exception), 0)
            summary = app.dataframe[-1].value
            self.assertEqual(summary.loc["NCS::OSEBERG", "currency"], "USD")
            self.assertAlmostEqual(summary.loc["NCS::OSEBERG", "investment_million"], 158.9)
            app.checkbox(key="cost_inflation").check().run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("Upload your completed inflation index" in item.value for item in app.info))
            app.checkbox(key="cost_inflation").uncheck().run()
            app.multiselect(key="bm_hc").select("OIL").run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("No investment records" in item.value for item in app.info))


if __name__ == "__main__":
    unittest.main()
