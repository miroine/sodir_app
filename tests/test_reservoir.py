import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from io import BytesIO
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from utils.reservoir import combined_parameters, field_parameters, parse_observation_upload
from utils.extract import facts_table
from utils.pt import normalise_pt
from test_dashboard import datasets, ROOT


class ReservoirObservationTests(unittest.TestCase):
    def test_combines_official_facts_without_promoting_estimates_or_legacy_seeds(self):
        tables = datasets()
        facts = facts_table(tables["description"])
        pt = normalise_pt(pd.DataFrame([dict(field="OSEBERG", pressure=300, temperature=110,
                                             source="legacy report", confidence="unverified")]))
        result = combined_parameters("OSEBERG", tables["overview"], facts, curated=pt,
                                     geometry={"outline_area_km2": 175.68},
                                     reservoir_text="Porosity is 20-30 per cent; permeability is 100-500 mD. Viscosity is 0.4 cP.")
        official = result.loc[result["quality"].eq("Source-backed")]
        self.assertIn("Reservoir depth", official["parameter"].tolist())
        self.assertIn("Hydrocarbon type", official["parameter"].tolist())
        self.assertIn("Field-outline footprint proxy", official["parameter"].tolist())
        porosity = official.loc[official["parameter"].eq("Porosity")].iloc[0]
        self.assertEqual(porosity["value_min"], 20)
        self.assertEqual(porosity["value_max"], 30)
        self.assertEqual(porosity["unit"], "%")
        self.assertIn("20-30 per cent", porosity["source_locator"])
        self.assertTrue(result.loc[result["dataset"].eq("Existing P/T table"), "quality"].eq("Provisional / unverified").all())
        self.assertTrue(result.loc[result["dataset"].eq("Depth-based model"), "quality"].eq("Estimate").all())
        self.assertTrue(official["source_url"].str.startswith("https://").all())
        # A second field still gets its official classification, without literature observations.
        empty = combined_parameters("EMPTY", tables["overview"], facts, curated=pt)
        self.assertEqual(empty["parameter"].tolist(), ["Hydrocarbon type"])

    def test_upload_validation_preserves_sources_units_and_field_scope(self):
        row = dict(field=" oseberg ", parameter="Porosity", value_min=0.2, value_max=0.3,
                   unit="fraction", reservoir="Tarbert", conditions="Core, 250 bar confining stress",
                   source_title="Core report", source_url="https://example.org/report",
                   source_locator="Table 2", well="30/9-B-1 H")
        raw = pd.DataFrame([row])
        parsed = parse_observation_upload(raw.to_csv(index=False).encode(), "core.csv", ["OSEBERG", "EMPTY"])
        self.assertEqual(parsed.iloc[0]["field"], "OSEBERG")
        self.assertEqual(parsed.iloc[0]["quality"], "User supplied")
        self.assertEqual(parsed.iloc[0]["unit"], "fraction")
        output = BytesIO()
        raw.to_excel(output, index=False)
        excel = parse_observation_upload(output.getvalue(), "core.xlsx", ["OSEBERG"])
        self.assertEqual(excel.iloc[0]["source_url"], row["source_url"])
        for column, value in (("field", "MISSPELLED"), ("conditions", ""), ("source_url", "file:///private"),
                              ("value_max", 0.1), ("value_min", "inf")):
            invalid = raw.copy()
            invalid[column] = value
            with self.assertRaises(ValueError):
                parse_observation_upload(invalid.to_csv(index=False).encode(), "core.csv", ["OSEBERG"])
        tables = datasets()
        result = combined_parameters("OSEBERG", tables["overview"], facts_table(tables["description"]), user=parsed)
        user = result.loc[result["dataset"].eq("User observations")]
        self.assertEqual(len(user), 1)
        self.assertEqual(user.iloc[0]["well"], "30/9-B-1 H")

    def test_well_intervals_stay_well_scoped_and_uploads_retain_confidence(self):
        tables = datasets()
        tops = pd.DataFrame({"wlbName": ["30/9-B-1 H", "other"], "lsuName": ["TARBERT FM"] * 2,
                             "lsuTopDepth": [2500, 1000], "lsuBottomDepth": [2600, 2000]})
        user_pt = normalise_pt(pd.DataFrame([dict(field="OSEBERG", pressure=300, source="my PVT file")]))
        result = combined_parameters("OSEBERG", tables["overview"], facts_table(tables["description"]),
                                     wells=tables["wells"], tops=tops, pt_upload=user_pt)
        intervals = result.loc[result["dataset"].eq("SODIR formation tops")]
        self.assertEqual(len(intervals), 1)
        self.assertEqual(intervals.iloc[0]["well"], "30/9-B-1 H")
        self.assertIn("NOT producing thickness", intervals.iloc[0]["conditions"])
        self.assertEqual(result.loc[result["dataset"].eq("User P/T upload"), "quality"].tolist(), ["User supplied"])

    def test_overview_defaults_hide_uncertain_rows_and_combines_retained_upload(self):
        tables = datasets()
        with patch("utils.data.load_dataset", side_effect=lambda name: tables[name]):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            self.assertEqual(len(app.exception), 0)
            visible = app.dataframe[-1].value
            self.assertTrue(visible["quality"].eq("Source-backed").all())
            self.assertIn("Reservoir depth", visible["parameter"].tolist())
            app.checkbox(key="bm_reservoir_estimates").check().run()
            self.assertEqual(len(app.exception), 0)
            self.assertIn("Estimate", app.dataframe[-1].value["quality"].tolist())
            app.sidebar.radio[0].set_value("Production").run()
            app.sidebar.radio[0].set_value("Overview").run()
            self.assertTrue(app.checkbox(key="bm_reservoir_estimates").value)
            app.checkbox(key="bm_reservoir_inventory").check().run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("Download all-field combined observations CSV" in str(button.proto)
                                for button in app.get("download_button")))
            profile = BytesIO(
                b"field,parameter,value_min,unit,reservoir,conditions,source_title,source_url,source_locator\n"
                b"OSEBERG,Porosity,0.2,fraction,Tarbert,Core analysis,Core report,https://example.org/report,Table 2\n")
            profile.name = "reservoir.csv"
            app.session_state["saved_uploads"] = {"bm_reservoir_upload": profile}
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("User observations" in str(frame.value) for frame in app.dataframe))
            app.sidebar.radio[0].set_value("Production").run()
            app.sidebar.radio[0].set_value("Overview").run()
            self.assertEqual(len(app.exception), 0)
            app.button(key="bm_reservoir_upload_clear").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertNotIn("bm_reservoir_upload", app.session_state["saved_uploads"])

    def test_known_field_observations_preserve_sources_and_conditions(self):
        data = field_parameters("kvitebjørn")
        self.assertFalse(data.empty)
        self.assertTrue(data["source_url"].str.startswith("https://").all())
        self.assertTrue(data["conditions"].ne("").all())
        self.assertTrue(data["evidence_status"].ne("").all())
        self.assertIn("HPHT", data["parameter"].tolist())
        permeability = data.loc[data["parameter"].eq("Reported average permeability - Tarbert")].iloc[0]
        self.assertEqual(float(permeability["value_min"]), 60)
        self.assertEqual(float(permeability["value_max"]), 75)
        self.assertIn("Provisional", permeability["evidence_status"])
        porosity = data.loc[data["parameter"].str.startswith("Porosity")].iloc[0]
        self.assertEqual(porosity["value_min"], "Not verified")
        self.assertTrue(field_parameters("UNREVIEWED FIELD").empty)

    def test_missing_provenance_is_rejected(self):
        data = field_parameters("KVITEBJØRN")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "observations.csv"
            data.loc[0, "source_url"] = ""
            data.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                field_parameters("KVITEBJØRN", path)
            data.drop(columns=["conditions"]).to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "provenance"):
                field_parameters("KVITEBJØRN", path)
