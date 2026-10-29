import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.reservoir import field_parameters


class ReservoirObservationTests(unittest.TestCase):
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
