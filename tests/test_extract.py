import unittest

import pandas as pd

from utils import extract
from utils.pt import estimate_from_depth, load_curated, normalise_pt, pt_for_fields

OSEBERG = {
    "Development": "Oseberg is a field in the northern part of the North Sea. The water depth is 100 metres. Oseberg was "
                   "discovered in 1979, and the plan for development and operation (PDO) was approved in 1984. The field was "
                   "developed in multiple phases and the production started in 1988. A PDO for the western flank was approved "
                   "in 2003 and included a subsea template tied-back to Oseberg B. The platform receives power from shore.",
    "Reservoir": "Oseberg produces oil and gas from sandstone of Middle Jurassic age in the Brent Group. The main reservoirs "
                 "are in the Oseberg and Tarbert Formations, but there is also production from the Etive and Ness Formations. "
                 "The reservoirs are at depths of 2300-2700 metres and have generally good quality. The satellite structures "
                 "also produce from the Statfjord Group and Cook Formation.",
    "Recovery strategy": "The Oseberg field is produced by pressure depletion, as well as pressure maintenance using gas and "
                         "water injection in some structures. Massive upflank gas injection in the main field has provided "
                         "excellent oil displacement, and a large gas cap has developed.",
    "Transport": "",
    "Status": "New production wells are continuously being drilled.",
}
TROLL_RECOVERY = ("The gas in Troll Øst is recovered by pressure depletion through 39 wells drilled from Troll A. The recovery "
                  "strategy is based primarily on pressure depletion, but this is accompanied by a simultaneous expansion of both "
                  "the gas cap above the oil zone and the underlying water zone. Some gas is also reinjected. Produced water was "
                  "reinjected into the northern part of the Troll Vest oil province from 2000 to 2016.")
GULLFAKS_RESERVOIR = ("Gullfaks produces oil from Middle Jurassic sandstone in the Brent Group, and from Lower Jurassic and Upper "
                      "Triassic sandstone in the Statfjord Group and Cook and Lunde Formations. Recoverable oil is also present in "
                      "fractured carbonate and shale in the overlying Shetland Group and Lista Formation. The reservoirs are at "
                      "depths of 1700-2000 metres in rotated fault blocks.")


class ExtractionTests(unittest.TestCase):
    def test_oseberg_facts(self):
        facts = extract.extract_field_facts(OSEBERG)
        self.assertEqual(facts["formations"], ["Oseberg", "Tarbert", "Etive", "Ness", "Cook"])
        self.assertEqual(facts["groups"], ["Brent", "Statfjord"])
        self.assertEqual(facts["ages"], ["Middle Jurassic"])
        self.assertEqual(facts["lithology"], ["sandstone"])
        self.assertEqual((facts["depth_min_m"], facts["depth_max_m"], facts["depth_mid_m"]), (2300, 2700, 2500))
        self.assertEqual((facts["water_depth_min_m"], facts["water_depth_max_m"]), (100, 100))
        self.assertEqual(facts["drainage_strategy"], "Water & gas injection")
        self.assertIn("Gas cap expansion", facts["mechanisms"])
        self.assertEqual((facts["discovery_year"], facts["pdo_year"], facts["production_start_text"]), (1979, 1984, 1988))
        self.assertEqual(facts["development_phases"], 2)
        self.assertIn("Subsea tie-back", facts["concept"])
        self.assertIn("Power from shore", facts["concept"])
        self.assertEqual(facts["reservoir_quality"], "good")
        self.assertFalse(facts["hpht"])

    def test_primary_clause_beats_secondary_mechanisms(self):
        mechanisms = extract.extract_tags(TROLL_RECOVERY, extract.DRIVE_TAGS)
        self.assertIn("Water injection", mechanisms)
        self.assertEqual(extract.primary_drive(TROLL_RECOVERY, mechanisms), "Pressure depletion")
        self.assertEqual(extract.classify_drive(["WAG", "Water injection"]), "WAG")
        self.assertEqual(extract.classify_drive(["Gas lift"]), "Not stated")
        self.assertEqual(extract.classify_drive(["Natural water drive", "Pressure depletion"]), "Natural water drive")

    def test_group_names_do_not_leak_into_formations(self):
        self.assertEqual(extract.extract_formations(GULLFAKS_RESERVOIR), ["Cook", "Lunde", "Lista"])
        self.assertEqual(extract.extract_groups(GULLFAKS_RESERVOIR), ["Brent", "Statfjord", "Shetland"])
        self.assertEqual(extract.extract_formations("The main reservoir contains oil in Upper Jurassic intra-Draupne sandstone."), ["Draupne"])
        self.assertEqual(extract.extract_formations("The main reservoir is in the Upper Cretaceous Tor Formation, at a depth of 3200 metres."), ["Tor"])
        self.assertEqual(extract.extract_ages("Late Cretaceous age in the Tor Formation and early Paleocene age in the Ekofisk Formation"),
                         ["Late Cretaceous", "Early Paleocene"])

    def test_depth_ignores_water_depth_and_handles_phrasings(self):
        self.assertEqual(extract.extract_reservoir_depth("The water depth is 300 metres. The reservoir depth is 1900 metres."), (1900, 1900))
        self.assertEqual(extract.extract_reservoir_depth("The reservoir is at a depth of more than 4,000 metres."), (4000, 4000))
        self.assertEqual(extract.extract_reservoir_depth("Reservoirs at a depth of 3000 metres and the Jurassic reservoirs at about 3600-4000 metres."), (3000, 4000))
        self.assertEqual(extract.extract_reservoir_depth("No depth here."), (None, None))
        self.assertEqual(extract.extract_water_depth("The water depth is 130-220 metres."), (130, 220))

    def test_well_counts_recovery_factor_years_and_hpht(self):
        text = ("The field is developed with two horizontal production wells and one water injection well. Eight subsea "
                "templates with a total of 32 well slots are tied-back to the FPSO. Currently, there are four active producers.")
        self.assertEqual(extract.extract_well_counts(text), (2, 1, 32))
        self.assertEqual(extract.extract_recovery_factor(
            "had an expected recovery factor of 17 per cent. The expected final recovery factor is now estimated to be over 50 per cent."),
            (0.17, 0.50))
        self.assertEqual(extract.extract_recovery_factor("the field has a relatively low recovery factor."), (None, None))
        years = extract.extract_years("Johan Sverdrup was discovered in 2010 and the PDO for Phase I was approved in 2015. "
                                      "In 2019, the production from Phase I started and the PDO for Phase II was approved. "
                                      "The production from Phase II started in 2022.")
        self.assertEqual((years["discovery_year"], years["pdo_year"], years["production_start_text"], years["development_phases"]), (2010, 2015, 2019, 2))
        self.assertTrue(extract.hpht_flag("has high pressure and high temperature (HPHT)"))
        self.assertEqual(extract.extract_pressure_temperature("initial pressure of 450 bar and 150 °C"), (450, 150))
        self.assertEqual(extract.extract_sub_area("Gullfaks is a field in the Tampen area in the northern part of the North Sea."), "Tampen")
        self.assertEqual(extract.extract_sub_area("Edvard Grieg is a field in the Utsira High area in the central North Sea"), "Utsira High")

    def test_facts_table_from_description_frame(self):
        descriptions = pd.DataFrame({
            "fldName": ["OSEBERG"] * 3 + ["EMPTY"],
            "fldDescriptionHeading": ["Development", "Reservoir", "Recovery strategy", "Reservoir"],
            "fldDescriptionText": [OSEBERG["Development"], OSEBERG["Reservoir"], OSEBERG["Recovery strategy"], None],
        })
        table = extract.facts_table(descriptions)
        self.assertEqual(table.loc["OSEBERG", "main_formation"], "Oseberg")
        self.assertEqual(table.loc["OSEBERG", "main_group"], "Brent")
        self.assertEqual(table.loc["EMPTY", "formations"], [])
        self.assertEqual(table.loc["EMPTY", "drainage_strategy"], "Not stated")
        self.assertTrue(extract.facts_table(pd.DataFrame()).empty)


class PressureTemperatureTests(unittest.TestCase):
    def test_curated_table_loads_and_estimates_fall_back(self):
        curated = load_curated()
        self.assertIn("EKOFISK", set(curated["field"]))
        self.assertEqual(estimate_from_depth(2000, 100), (202, 70))
        self.assertEqual(estimate_from_depth(None), (None, None))
        facts = pd.DataFrame({
            "depth_mid_m": [3200.0, 2000.0, 4500.0, None],
            "water_depth_min_m": [70.0, 100.0, 300.0, None],
            "hpht": [False, False, True, False],
            "pressure_bar_text": [None, None, None, None],
            "temperature_c_text": [None, None, 160, None],
        }, index=pd.Index(["EKOFISK", "NEWFIELD", "DEEPFIELD", "BLANK"], name="fldName"))
        table = pt_for_fields(facts, curated=curated)
        self.assertEqual(table.loc["EKOFISK", "pressure_bar"], 492)
        self.assertEqual(table.loc["EKOFISK", "confidence"], "high")
        self.assertEqual(table.loc["NEWFIELD", "confidence"], "estimate")
        self.assertEqual(table.loc["NEWFIELD", "pressure_bar"], 202)
        self.assertTrue(pd.isna(table.loc["DEEPFIELD", "pressure_bar"]))
        self.assertEqual(table.loc["DEEPFIELD", "temperature_c"], 160)
        self.assertTrue(pd.isna(table.loc["BLANK", "pressure_bar"]))

    def test_user_table_overrides_and_accepts_aliases(self):
        user = normalise_pt(pd.DataFrame({"Field": [" ekofisk "], "Pressure (bar)": [500], "Temp": [130]}))
        self.assertEqual(user.loc[0, "field"], "EKOFISK")
        facts = pd.DataFrame({"depth_mid_m": [3200.0], "water_depth_min_m": [70.0], "hpht": [False],
                              "pressure_bar_text": [None], "temperature_c_text": [None]},
                             index=pd.Index(["EKOFISK"], name="fldName"))
        table = pt_for_fields(facts, user_table=user)
        self.assertEqual(table.loc["EKOFISK", "pressure_bar"], 500)
        self.assertTrue(str(table.loc["EKOFISK", "source"]).startswith("User table"))


if __name__ == "__main__":
    unittest.main()
