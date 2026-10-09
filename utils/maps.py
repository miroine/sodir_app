from html import escape
import json
from math import isfinite
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
import xml.etree.ElementTree as ET

import streamlit as st

from utils.data import DataUnavailable


WMS_URL = "https://factmaps.sodir.no/api/services/Factmaps/FactMapsWGS84/MapServer/WMSServer"
FIELD_URL = "https://factmaps.sodir.no/api/rest/services/DataService/Data/MapServer/7100/query"


def fetch_map_data(url):
    with urlopen(url, timeout=15) as response:
        content = response.read(5_000_001)
    if len(content) > 5_000_000:
        raise ValueError("SODIR map response is too large.")
    return content


def parse_layers(content):
    if b"<!DOCTYPE" in content.upper():
        raise ValueError("Unexpected WMS document.")
    root = ET.fromstring(content)
    layers = {}

    def visit(element, inherited_crs):
        crs = inherited_crs | {
            value
            for child in element
            if child.tag.split("}")[-1] in ("CRS", "SRS")
            for value in (child.text or "").split()
        }
        name = element.findtext("{*}Name")
        title = element.findtext("{*}Title")
        if name and "EPSG:3857" in crs:
            layers[name] = title or name
        for child in element.findall("{*}Layer"):
            visit(child, crs)

    for layer in root.findall("./{*}Capability/{*}Layer"):
        visit(layer, set())
    if not layers:
        raise ValueError("No compatible SODIR map layers found.")
    return layers


@st.cache_data(ttl=86400, max_entries=1, show_spinner=False)
def load_map_layers():
    try:
        query = urlencode(dict(service="WMS", request="GetCapabilities", version="1.3.0"))
        return parse_layers(fetch_map_data(f"{WMS_URL}?{query}"))
    except (OSError, ValueError, ET.ParseError) as exc:
        raise DataUnavailable("SODIR layer catalogue is temporarily unavailable.") from exc


def valid_point(point):
    return (
        isinstance(point, (list, tuple)) and len(point) >= 2
        and all(isinstance(value, (int, float)) and not isinstance(value, bool)
                and isfinite(value) for value in point[:2])
        and -180 <= point[0] <= 180 and -90 <= point[1] <= 90
    )


def parse_field_geometry(payload, field_id):
    if not isinstance(payload, dict) or payload.get("error"):
        raise ValueError("Invalid SODIR geometry response.")
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("Missing field features.")
    lines, points = [], []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        attributes = feature.get("attributes") or {}
        if not isinstance(attributes, dict):
            continue
        try:
            matches = float(attributes.get("fldNpdidField")) == field_id
        except (TypeError, ValueError):
            matches = False
        if not matches:
            continue
        geometry = feature.get("geometry") or {}
        if not isinstance(geometry, dict):
            continue
        paths = geometry.get("rings", geometry.get("paths", []))
        for path in paths if isinstance(paths, list) else []:
            if isinstance(path, list) and len(path) >= 2 and all(valid_point(point) for point in path):
                lines.append([[point[1], point[0]] for point in path])
        point = [geometry.get("x"), geometry.get("y")]
        if valid_point(point):
            points.append([point[1], point[0]])
    if not lines and not points:
        raise ValueError("No valid boundary or location is available for this field.")
    return dict(lines=lines, points=points)


@st.cache_data(ttl=86400, max_entries=128, show_spinner=False)
def load_field_geometry(field_id):
    if isinstance(field_id, bool) or not isinstance(field_id, int) or field_id <= 0:
        raise ValueError("A positive integer SODIR field ID is required.")
    query = urlencode(dict(
        where=f"fldNpdidField={field_id}", outFields="fldNpdidField",
        returnGeometry="true", outSR=4326, f="json",
    ))
    try:
        payload = json.loads(fetch_map_data(f"{FIELD_URL}?{query}"))
        return parse_field_geometry(payload, field_id)
    except (OSError, ValueError, TypeError) as exc:
        raise DataUnavailable("Selected-field geometry is temporarily unavailable.") from exc


def map_document(selected_field, geometry, layers, dark=False):
    payload = json.dumps(
        dict(
            field=selected_field, geometry=geometry, wms=WMS_URL,
            layers=[dict(name=name, title=escape(title)) for name, title in layers.items()],
            dark=dark,
        ),
        allow_nan=False,
    ).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    template = (Path(__file__).resolve().parent / "map.html").read_text()
    return template.replace("__MAP_DATA__", payload)
