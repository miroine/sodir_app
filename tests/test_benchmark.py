import unittest

import pandas as pd

from utils import benchmark as bm
from utils import figures
from utils.extract import facts_table
from utils.pt import pt_for_fields
from test_dashboard import datasets


def master_tables(current_year=2025):
    tables = datasets()
    facts = facts_table(tables["description"])
    pt = pt_for_fields(facts)
    master = bm.build_master(tables["overview"], tables["reserves"], tables["inplace"], tables["yearly"],
                             tables["wells"], facts, pt, current_year=current_year)
    return master, tables


class BenchmarkTests(unittest.TestCase):
    def test_master_table_metrics(self):
        master, tables = master_tables()
        row = master.loc["OSEBERG"]
        self.assertEqual(row["start_year"], 2021)
        self.assertEqual(row["years_on_production"], 4)
        self.assertEqual(row["peak_year"], 2022)
        self.assertEqual(row["years_to_peak"], 2)
        self.assertAlmostEqual(row["cum_oe"], 36.0)
        self.assertAlmostEqual(row["inplace_gas"], 0.3)
        self.assertAlmostEqual(row["rf_oil"], 0.7)
        self.assertAlmostEqual(row["rf_gas"], 1 / 3)
        self.assertEqual((row["producers_drilled"], row["producers_active"], row["injectors_drilled"], row["injectors_active"]), (2, 1, 1, 1))
        self.assertEqual(row["observation_wells"], 1)
        self.assertAlmostEqual(row["injector_producer_ratio"], 0.5)
        self.assertAlmostEqual(row["reserves_per_producer"], 70.1 / 2)
        self.assertAlmostEqual(row["peak_offtake_pct"], 100 * 12 / 70.1)
        self.assertEqual(row["drainage_strategy"], "Water & gas injection")
        self.assertEqual(row["main_formation"], "Oseberg")
        self.assertEqual(row["hc_type"], "OIL/GAS")
        self.assertEqual(row["pt_confidence"], "medium")
        self.assertEqual(master.loc["EMPTY", "drainage_strategy"], "Not stated")
        self.assertEqual(master.loc["EMPTY", "formations"], [])
        self.assertTrue(pd.isna(master.loc["EMPTY", "start_year"]))

    def test_current_year_is_excluded_and_threshold_moves_start(self):
        master, _ = master_tables(current_year=2024)
        self.assertEqual(master.loc["OSEBERG", "last_year"], 2023)
        tables = datasets()
        summary = bm.production_summary(tables["yearly"], current_year=2025, start_threshold=0.6)
        self.assertEqual(summary.loc["OSEBERG", "start_year"], 2022)
        self.assertEqual(summary.loc["OSEBERG", "first_reported_year"], 2021)

    def test_implausible_recovery_factors_are_blanked_but_kept_raw(self):
        tables = datasets()
        tables["reserves"]["fldRecoverableOil"] = 150.0
        master = bm.build_master(tables["overview"], tables["reserves"], tables["inplace"], tables["yearly"],
                                 tables["wells"], pd.DataFrame(), None, current_year=2025)
        self.assertTrue(pd.isna(master.loc["OSEBERG", "rf_oil"]))
        self.assertAlmostEqual(master.loc["OSEBERG", "rf_oil_raw"], 1.5)

    def test_producers_by_year_respects_plugging(self):
        tables = datasets()
        counts = bm.producers_by_year(tables["wells"], 2025).set_index("year")["producers"]
        self.assertEqual(counts.loc[2021], 2)
        self.assertEqual(counts.loc[2023], 2)
        self.assertEqual(counts.loc[2024], 1)

    def test_normalised_profiles_and_envelope(self):
        master, tables = master_tables()
        absolute = bm.normalised_profiles(tables["yearly"], master, "oe", "absolute", current_year=2025)
        self.assertEqual(absolute["years_on"].tolist(), [1, 2, 3, 4])
        self.assertEqual(absolute["value"].tolist(), [6.0, 12.0, 10.0, 8.0])
        pct = bm.normalised_profiles(tables["yearly"], master, "oil", "pct_recoverable", current_year=2025)
        self.assertAlmostEqual(pct["value"].iloc[1], 100 * 10 / 70)
        inplace = bm.normalised_profiles(tables["yearly"], master, "oil", "pct_inplace", current_year=2025)
        self.assertAlmostEqual(inplace["value"].iloc[1], 10.0)
        per_well = bm.normalised_profiles(tables["yearly"], master, "oe", "per_well", wells=tables["wells"], current_year=2025)
        self.assertAlmostEqual(per_well.loc[per_well["year"] == 2024, "value"].iloc[0], 8.0)
        self.assertAlmostEqual(per_well.loc[per_well["year"] == 2022, "value"].iloc[0], 6.0)
        env = bm.envelope(absolute, min_fields=1)
        self.assertEqual(env["p50"].tolist(), [6.0, 12.0, 10.0, 8.0])
        self.assertTrue(bm.envelope(absolute, min_fields=3).empty)
        with self.assertRaises(ValueError):
            bm.normalised_profiles(tables["yearly"], master, "oe", "bogus")

    def test_ratios(self):
        master, tables = master_tables()
        table = bm.ratios(tables["yearly"], master, current_year=2025).set_index("year")
        self.assertAlmostEqual(table.loc[2022, "gor"], 200.0)
        self.assertAlmostEqual(table.loc[2024, "water_cut"], 0.5)
        self.assertAlmostEqual(table.loc[2022, "gas_share"], 2 / 12)

    def test_filters(self):
        master, _ = master_tables()
        self.assertEqual(bm.apply_filters(master, hc_types=["OIL/GAS"]).sum(), 1)
        self.assertEqual(bm.apply_filters(master, formations=["tarbert"]).sum(), 1)
        self.assertEqual(bm.apply_filters(master, groups=["Brent"]).sum(), 1)
        self.assertEqual(bm.apply_filters(master, drives=["WAG"]).sum(), 0)
        self.assertEqual(bm.apply_filters(master, inplace_range=(0, 50), include_missing=False).sum(), 0)
        self.assertEqual(bm.apply_filters(master, inplace_range=(0, 50), include_missing=True).sum(), 1)
        self.assertEqual(bm.apply_filters(master, min_years=4).sum(), 1)
        self.assertEqual(bm.apply_filters(master, min_years=5).sum(), 0)
        self.assertEqual(bm.apply_filters(master, hpht=True).sum(), 0)

    def test_profile_upload_and_type_curve(self):
        csv = b"Year;Oil (million Sm3);Gas (billion Sm3);Water;Wells\n2030;1,0;0,5;0,1;4\n2031;2,0;1,0;0,3;6\n"
        profile = bm.parse_profile_upload(csv.replace(b",", b"."))
        self.assertEqual(profile["year"].tolist(), [2030, 2031])
        self.assertEqual(profile["oe"].tolist(), [1.5, 3.0])
        normalised = bm.normalise_upload(profile, "oe", "pct_recoverable", recoverable=30)
        self.assertEqual(normalised["value"].tolist(), [5.0, 10.0])
        per_well = bm.normalise_upload(profile, "oil", "per_well")
        self.assertEqual(per_well["value"].tolist(), [0.25, 1 / 3])
        with self.assertRaises(ValueError):
            bm.parse_profile_upload(b"a,b\n1,2\n")
        with self.assertRaises(ValueError):
            bm.parse_profile_upload(b"year,wells\n2030,2\n")
        env = pd.DataFrame({"years_on": [1, 2, 3], "p50": [10.0, 20.0, 10.0], "mean": [12.0, 18.0, 10.0], "p10": [1, 2, 3], "p90": [3, 4, 5], "n": [5, 5, 5]})
        curve = bm.type_curve(env, 50, 2030)
        self.assertEqual(curve["year"].tolist(), [2030, 2031, 2032])
        self.assertEqual(curve["value"].tolist(), [5.0, 10.0, 5.0])
        self.assertAlmostEqual(curve["cumulative"].iloc[-1], 20.0)
        rescaled = bm.type_curve(env, 50, 2030, rescale=True)
        self.assertAlmostEqual(rescaled["cumulative"].iloc[-1], 50.0)
        self.assertTrue(bm.type_curve(env, 0, 2030).empty)

    def test_figures_build_without_errors(self):
        master, tables = master_tables()
        profiles = bm.normalised_profiles(tables["yearly"], master, "oe", "absolute", current_year=2025)
        env = bm.envelope(profiles, min_fields=1)
        upload = bm.normalise_upload(bm.parse_profile_upload(b"year,oil,gas\n2030,1,0.5\n2031,2,1\n"), "oe", "absolute")
        figures.profile_figure(profiles, env, master, highlight="OSEBERG", upload=upload, log_y=True).to_json()
        figures.rf_scatter(master, "oil", highlight="OSEBERG").to_json()
        figures.rf_bars(master, "oil").to_json()
        figures.wells_scatter(master, highlight="OSEBERG").to_json()
        figures.box_by_category(master, "reserves_per_producer", "drainage_strategy", "t", "y", highlight="OSEBERG", log=True).to_json()
        figures.ratio_figure(bm.ratios(tables["yearly"], master, current_year=2025), "water_cut", master, highlight="OSEBERG").to_json()
        figures.pt_figure(master, highlight="OSEBERG").to_json()
        figures.wells_timeline(tables["wells"]).to_json()
        self.assertIsNone(figures.yearly_field_figure(pd.DataFrame()))
        coverage = bm.coverage(master, ["start_year", "formations", "missing_column"])
        self.assertEqual(coverage["attribute"].tolist(), ["start_year", "formations"])
        self.assertEqual(coverage["fields_with_value"].tolist(), [1, 1])


if __name__ == "__main__":
    unittest.main()
