from io import BytesIO
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from pyproj import Geod

from streamlit.testing.v1 import AppTest

from utils.data import DataUnavailable
from utils.maps import (
    load_field_geometry, load_map_layers, map_document, parse_field_geometry, parse_layers,
)
from test_dashboard import ROOT, datasets


CAPABILITIES = b"""<WMS_Capabilities xmlns="http://www.opengis.net/wms">
<Capability><Layer><Title>SODIR</Title><CRS>EPSG:3857</CRS>
<Layer><Name>36</Name><Title>Fields</Title></Layer>
<Layer><Name>61</Name><Title>Facilities</Title></Layer>
</Layer></Capability></WMS_Capabilities>"""


def feature(field_id):
    return dict(features=[dict(
        attributes=dict(fldNpdidField=field_id),
        geometry=dict(rings=[[[3, 60], [4, 60], [4, 61], [3, 60]]]),
    )])


class MapTests(unittest.TestCase):
    def test_geodesic_outline_area_subtracts_holes_and_sums_multipart(self):
        outer = [[3, 60], [3, 61], [4, 61], [4, 60], [3, 60]]
        hole = [[3.2, 60.2], [3.8, 60.2], [3.8, 60.8], [3.2, 60.8], [3.2, 60.2]]
        island = [[5, 60], [5, 60.1], [5.1, 60.1], [5.1, 60], [5, 60]]
        payload = {"features": [{"attributes": {"fldNpdidField": 123},
                                 "geometry": {"rings": [outer, hole, island]}}]}
        geod = Geod(ellps="WGS84")
        areas = [abs(geod.polygon_area_perimeter(*zip(*ring))[0]) for ring in [outer, hole, island]]
        expected = (areas[0] - areas[1] + areas[2]) / 1e6
        result = parse_field_geometry(payload, 123)
        self.assertAlmostEqual(result["outline_area_km2"], expected, places=8)
        # A one-degree cell at 60 N has roughly half the area of its equatorial counterpart.
        self.assertGreater(result["outline_area_km2"], 3900)
        self.assertLess(result["outline_area_km2"], 4100)
        point = {"features": [{"attributes": {"fldNpdidField": 123}, "geometry": {"x": 3, "y": 60}}]}
        self.assertIsNone(parse_field_geometry(point, 123)["outline_area_km2"])
        line = {"features": [{"attributes": {"fldNpdidField": 123}, "geometry": {"paths": [outer]}}]}
        self.assertIsNone(parse_field_geometry(line, 123)["outline_area_km2"])
        for rings in ([outer[:-1]], [[[3, 60], [None, 61], [4, 60], [3, 60]]]):
            payload["features"][0]["geometry"]["rings"] = rings
            with self.assertRaises(ValueError):
                parse_field_geometry(payload, 123)
        payload["exceededTransferLimit"] = True
        with self.assertRaisesRegex(ValueError, "incomplete"):
            parse_field_geometry(payload, 123)

    def test_overview_exposes_outline_area_with_explicit_proxy_label(self):
        tables = datasets()
        geometry = parse_field_geometry(feature(43625), 43625)
        with (
            patch("utils.data.load_dataset", side_effect=lambda name: tables[name]),
            patch("utils.maps.load_field_geometry", return_value=geometry) as loader,
            patch("utils.maps.load_map_layers", return_value={"36": "Fields"}),
        ):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            loader.assert_not_called()
            app.checkbox(key="map_outline_load").check().run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any(m.label == "SODIR field-outline area" and "km²" in m.value for m in app.metric))
            self.assertTrue(any("not measured net reservoir" in c.value for c in app.caption))
            self.assertTrue(any("Download field-outline area CSV" in str(b.proto) for b in app.get("download_button")))
            app.sidebar.radio[0].set_value("Map").run()
            app.sidebar.radio[0].set_value("Overview").run()
            self.assertTrue(app.checkbox(key="map_outline_load").value)

    def test_map_controls_survive_navigation_and_reset_when_field_changes(self):
        tables = datasets()
        with (
            patch("utils.data.load_dataset", side_effect=lambda name: tables[name]),
            patch("utils.maps.load_map_layers", return_value={"36": "Fields", "61": "Facilities"}),
            patch("utils.maps.load_field_geometry", return_value=parse_field_geometry(feature(43625), 43625)),
        ):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            app.sidebar.radio[0].set_value("Map").run()
            state_id = app.session_state["map_state_id"]
            self.assertIn(f'"state_id": "{state_id}"', app.get("iframe")[0].proto.srcdoc)
            app.multiselect(key="map_layers").set_value(["61"]).run()
            app.radio(key="map_mode").set_value("Official viewer").run()
            app.sidebar.radio[0].set_value("Overview").run()
            app.run()
            app.sidebar.radio[0].set_value("Map").run()
            self.assertEqual(app.radio(key="map_mode").value, "Official viewer")
            app.radio(key="map_mode").set_value("Layer controls").run()
            self.assertEqual(app.multiselect(key="map_layers").value, ["61"])
            self.assertEqual(app.session_state["map_state_id"], state_id)
            app.sidebar.selectbox[0].select("EMPTY").run()
            self.assertEqual(app.multiselect(key="map_layers").value, ["36"])
            self.assertNotEqual(app.session_state["map_state_id"], state_id)

    def tearDown(self):
        load_map_layers.clear()
        load_field_geometry.clear()

    def test_catalogue_inherits_projection_and_rejects_invalid_xml(self):
        self.assertEqual(parse_layers(CAPABILITIES), {"36": "Fields", "61": "Facilities"})
        for content in (
            b"<!DOCTYPE xml><WMS_Capabilities/>",
            CAPABILITIES.replace(b"EPSG:3857", b"EPSG:4326"),
        ):
            with self.assertRaises(ValueError):
                parse_layers(content)

    def test_geometry_is_validated_and_coordinates_are_swapped(self):
        geometry = parse_field_geometry(feature(43625), 43625)
        self.assertEqual(geometry["lines"][0][0], [60, 3])
        for payload in (
            feature(999), {"error": {"message": "unavailable"}}, {},
            {"features": [{"attributes": {"fldNpdidField": 43625}, "geometry": {
                "rings": [[[float("inf"), 60], [3, 61]]],
            }}]},
        ):
            with self.assertRaises(ValueError):
                parse_field_geometry(payload, 43625)
        geometry = parse_field_geometry({
            "features": [{"attributes": {"fldNpdidField": "43625"},
                          "geometry": {"x": 3.5, "y": 60.5}}],
        }, 43625)
        self.assertEqual(geometry["points"], [[60.5, 3.5]])

    def test_cache_query_field_id_and_service_errors(self):
        with patch("utils.maps.urlopen", return_value=BytesIO(CAPABILITIES)) as request:
            load_map_layers()
            load_map_layers()
            self.assertEqual(request.call_count, 1)
        import json
        with patch("utils.maps.urlopen", return_value=BytesIO(json.dumps(feature(43625)).encode())) as request:
            load_field_geometry(43625)
            load_field_geometry(43625)
            self.assertEqual(request.call_count, 1)
            query = parse_qs(urlparse(request.call_args.args[0]).query)
            self.assertEqual(query["where"], ["fldNpdidField=43625"])
            self.assertEqual(query["outSR"], ["4326"])
            self.assertEqual(request.call_args.kwargs["timeout"], 15)
        for field_id in ("43625 OR 1=1", -1, True):
            with self.assertRaises(ValueError):
                load_field_geometry(field_id)
        load_map_layers.clear()
        with patch("utils.maps.urlopen", side_effect=TimeoutError()):
            with self.assertRaises(DataUnavailable):
                load_map_layers()

    def test_document_does_not_inject_remote_labels_or_field_names(self):
        title = "</script><script>alert(1)</script>"
        html = map_document(
            title, parse_field_geometry(feature(43625), 43625), {"36": title}, dark=True,
        )
        self.assertNotIn(title, html)
        self.assertIn("\\u003c/script\\u003e", html)
        self.assertIn("textContent = data.field", html)
        self.assertIn("leaflet@1.9.4", html)
        self.assertIn("km²", html)
        self.assertNotIn("Â", html)
        for expected in (
            '"Dark":', '"Gray":', '"Satellite":', "L.Control.Draw",
            "L.Draw.Event.EDITED", "L.Draw.Event.DELETED", "radius_m",
            "application/geo+json", "geodesicArea", "map.distance",
        ):
            self.assertIn(expected, html)

    def test_dashboard_map_switches_geometry_without_loading_production(self):
        tables = datasets()
        with (
            patch("utils.data.load_dataset", side_effect=lambda name: tables[name]) as loader,
            patch("utils.maps.load_map_layers", return_value={"36": "Fields", "61": "Facilities"}),
            patch("utils.maps.load_field_geometry",
                  side_effect=lambda field_id: parse_field_geometry(feature(field_id), field_id)) as geometry,
        ):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            loader.reset_mock()
            app.sidebar.radio[0].set_value("Map").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual([call.args[0] for call in loader.call_args_list], ["overview"])
            self.assertEqual(geometry.call_args.args[0], 43625)
            self.assertIn('"field": "OSEBERG"', app.get("iframe")[0].proto.srcdoc)
            app.multiselect[0].set_value(["61"]).run()
            app.sidebar.selectbox[0].select("EMPTY").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(geometry.call_args.args[0], 999)
            self.assertEqual(app.multiselect[0].value, ["36"])
            self.assertIn('"field": "EMPTY"', app.get("iframe")[0].proto.srcdoc)

    def test_dashboard_falls_back_to_official_viewer(self):
        tables = datasets()
        with (
            patch("utils.data.load_dataset", side_effect=lambda name: tables[name]),
            patch("utils.maps.load_map_layers", side_effect=DataUnavailable("Layers unavailable")),
        ):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            app.sidebar.radio[0].set_value("Map").run()
            self.assertEqual(len(app.exception), 0)
            self.assertIn("Showing the official viewer", app.warning[0].value)
            self.assertIn("npdid=43625", app.get("iframe")[0].proto.src)


if __name__ == "__main__":
    unittest.main()
