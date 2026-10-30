"""Public NSTA adapters. Source blanks stay missing; UK records never acquire Norwegian tax/reserves."""
import json
from urllib.parse import quote, urlencode
from urllib.request import urlopen

import numpy as np
import pandas as pd
import streamlit as st

from utils.data import DataUnavailable, YEARLY_COLUMNS, prepare_monthly, prepare_wells
from utils.maps import parse_field_geometry

ROOT = "https://services-eu1.arcgis.com/OZMfUznmLTnWccBc/arcgis/rest/services/"
FIELDS = ROOT + "Offshore_hydrocarbon_fields_(WGS84)/FeatureServer/0"
PRODUCTION = ROOT + "UKCS_hydrocarbon_field_production_reports_PPRS_polygons_WGS84/FeatureServer/6"
WELLS = ROOT + quote("UKCS offshore petroleum wells bottom holes WGS84", safe="") + "/FeatureServer/0"
PORTAL = "https://opendata-nstauthority.hub.arcgis.com/"
VOLUMES = {"OILPRODM3": "prfPrdOilNetMillSm3", "GASPIPVOL": "prfPrdGasNetBillSm3",
           "GCONDVOL": "prfPrdCondensateNetMillSm3", "WATPRODVOL": "prfPrdProducedWaterInFieldMillSm3"}
PRODUCTION_WHERE = "LOCATION='OFFSHORE' AND UNITTYPCOD IN ('P','G','OTL')"
PRODUCTION_BASIS = "NSTA pipeline gas; oil+condensate+gas OE proxy; NGL unavailable"


def query(service, **parameters):
    """Bounded, ordered ArcGIS pagination; never accept a partial page as complete."""
    records = []
    offset = 0
    while offset < 250000:
        params = dict(f="json", where="1=1", outFields="*", returnGeometry="false",
                      orderByFields="OBJECTID", resultRecordCount=2000, resultOffset=offset)
        params.update(parameters)
        url = service + "/query?" + urlencode(params)
        try:
            with urlopen(url, timeout=60) as response:
                payload = json.load(response)
        except (OSError, ValueError) as exc:
            raise DataUnavailable("NSTA public data service could not be read. Retry or use NCS.") from exc
        if payload.get("error") or not isinstance(payload.get("features"), list):
            raise DataUnavailable("NSTA returned an invalid query response; no partial data used.")
        page = payload["features"]
        records.extend(page)
        if not payload.get("exceededTransferLimit"):
            return records
        if not page:
            raise DataUnavailable("NSTA pagination stopped before all records were returned.")
        offset += len(page)
    raise DataUnavailable("NSTA query exceeded the safe pagination limit.")


def attributes(records):
    try:
        return pd.DataFrame([record["attributes"] for record in records])
    except (KeyError, TypeError, ValueError) as exc:
        raise DataUnavailable("NSTA records have an invalid attribute schema.") from exc


def field_key(name):
    return "UKCS::" + str(name).strip().upper()


@st.cache_data(ttl=3600, show_spinner=False)
def load_fields():
    raw = attributes(query(FIELDS, outFields="OBJECTID,FIELDNAME,FIELDTYPE,STATUS,CURR_OPER,DEPTH_M,PROD_DATE,DISC_DATE,DISC_WELL"))
    if raw.empty or raw["FIELDNAME"].isna().any():
        raise DataUnavailable("NSTA offshore field catalogue is empty or invalid.")
    raw["FIELDNAME"] = raw["FIELDNAME"].str.strip().str.upper()
    if raw["FIELDNAME"].duplicated().any():
        raise DataUnavailable("NSTA field names are not unique; field identity needs review.")
    return raw.assign(
        fldName=raw["FIELDNAME"].map(field_key), field_name=raw["FIELDNAME"],
        country="UKCS", fldHcType=raw["FIELDTYPE"], fldCurrentActivitySatus=raw["STATUS"],
        fldMainArea="UKCS", cmpLongName=raw["CURR_OPER"],
    )


def converted_volumes(raw):
    raw = raw.copy()
    for source, target in VOLUMES.items():
        values = pd.to_numeric(raw[source], errors="raise")
        if (values.dropna() < 0).any() or np.isinf(values.dropna()).any():
            raise ValueError(f"NSTA {source} has invalid volumes.")
        # kSm3 gas / 1e6 = GSm3; m3 liquid / 1e6 = MSm3.
        raw[target] = values / 1e6
    raw["prfPrdNGLNetMillSm3"] = np.nan  # Not reported separately in this endpoint.
    raw["prfPrdOeNetMillSm3"] = raw[[VOLUMES[key] for key in ("OILPRODM3", "GASPIPVOL", "GCONDVOL")]].sum(axis=1, min_count=3)
    return raw


@st.cache_data(ttl=3600, show_spinner=False)
def load_yearly():
    stats = []
    for name in VOLUMES:
        stats.extend([
            dict(statisticType="sum", onStatisticField=name, outStatisticFieldName=name),
            dict(statisticType="count", onStatisticField=name, outStatisticFieldName="n_" + name),
        ])
    stats.extend([dict(statisticType="count", onStatisticField="OBJECTID", outStatisticFieldName="months"),
                  dict(statisticType="min", onStatisticField="PERIODMNTH", outStatisticFieldName="first_month"),
                  dict(statisticType="max", onStatisticField="PERIODMNTH", outStatisticFieldName="last_month")])
    raw = attributes(query(PRODUCTION, where=PRODUCTION_WHERE, outFields="",
                           groupByFieldsForStatistics="FIELDNAME,PERIODYR", outStatistics=json.dumps(stats),
                           orderByFields="FIELDNAME,PERIODYR"))
    if raw.empty:
        raise DataUnavailable("NSTA returned no offshore production history.")
    raw = raw.loc[raw["FIELDNAME"].isin(load_fields()["field_name"])].copy()
    if raw.duplicated(["FIELDNAME", "PERIODYR"]).any():
        raise DataUnavailable("NSTA annual pagination returned duplicate field-years.")
    # A missing month and a duplicate can cancel in a simple count/min/max check.
    duplicates = attributes(query(
        PRODUCTION, where=PRODUCTION_WHERE, outFields="",
        groupByFieldsForStatistics="FIELDNAME,PERIODYR,PERIODMNTH",
        outStatistics=json.dumps([dict(statisticType="count", onStatisticField="OBJECTID",
                                       outStatisticFieldName="records")]),
        having="COUNT(OBJECTID)>1", orderByFields="FIELDNAME,PERIODYR,PERIODMNTH",
    ))
    try:
        return prepare_annual(raw, duplicates)
    except (KeyError, ValueError, TypeError) as exc:
        raise DataUnavailable(f"NSTA annual production could not be normalized: {exc}") from exc


def prepare_annual(raw, duplicates):
    """Keep contiguous reporting boundaries; exclude missing interior months and duplicate units."""
    raw = raw.copy()
    raw["prfYear"] = pd.to_numeric(raw["PERIODYR"], errors="raise").astype(int)
    duplicate_years = set() if duplicates.empty else set(zip(duplicates["FIELDNAME"], duplicates["PERIODYR"]))
    months = pd.to_numeric(raw["months"], errors="raise")
    first = pd.to_numeric(raw["first_month"], errors="raise")
    last = pd.to_numeric(raw["last_month"], errors="raise")
    raw["reporting_months"] = months
    first_year = raw.groupby("FIELDNAME")["prfYear"].transform("min")
    last_year = raw.groupby("FIELDNAME")["prfYear"].transform("max")
    valid_boundary = (raw["prfYear"].eq(first_year) | first.eq(1)) & (raw["prfYear"].eq(last_year) | last.eq(12))
    duplicate_year = pd.Series([(field, year) in duplicate_years for field, year in zip(raw["FIELDNAME"], raw["PERIODYR"])],
                               index=raw.index)
    raw["complete_reporting"] = (months.eq(last - first + 1) & first.between(1, 12) & last.between(1, 12)
                                 & valid_boundary & ~duplicate_year)
    raw["partial_boundary_year"] = raw["complete_reporting"] & months.lt(12)
    raw["prfInformationCarrier"] = raw["FIELDNAME"].map(field_key)
    for name in VOLUMES:
        raw.loc[raw["n_" + name].ne(months), name] = np.nan
    raw = converted_volumes(raw)
    raw.loc[~raw["complete_reporting"], list(YEARLY_COLUMNS)] = np.nan
    return raw[["prfInformationCarrier", "prfYear", *YEARLY_COLUMNS, "reporting_months", "complete_reporting",
                "partial_boundary_year"]]


@st.cache_data(ttl=3600, max_entries=32, show_spinner=False)
def load_monthly(name):
    escaped = str(name).replace("'", "''")
    raw = attributes(query(PRODUCTION, where=PRODUCTION_WHERE + f" AND FIELDNAME='{escaped}'",
                           outFields="FIELDNAME,PERIODYR,PERIODMNTH," + ",".join(VOLUMES)))
    if raw.empty:
        return prepare_monthly(pd.DataFrame(columns=["prfYear", "prfMonth", "prfInformationCarrier"]))
    if raw.duplicated(["PERIODYR", "PERIODMNTH"]).any():
        raise DataUnavailable("Multiple NSTA reporting units per field-month; no double counting permitted.")
    try:
        raw = converted_volumes(raw)
        raw["prfYear"] = pd.to_numeric(raw["PERIODYR"], errors="raise").astype(int)
        raw["prfMonth"] = pd.to_numeric(raw["PERIODMNTH"], errors="raise").astype(int)
        if not raw["prfMonth"].between(1, 12).all():
            raise ValueError("Invalid reporting month.")
        raw["prfInformationCarrier"] = raw["FIELDNAME"].map(field_key)
        return prepare_monthly(raw).assign(country="UKCS", source=PRODUCTION, production_basis=PRODUCTION_BASIS)
    except (KeyError, ValueError, TypeError) as exc:
        raise DataUnavailable(f"NSTA monthly production could not be normalized: {exc}") from exc


@st.cache_data(ttl=86400, max_entries=32, show_spinner=False)
def load_wells(name):
    escaped = str(name).replace("'", "''")
    return attributes(query(WELLS, where=f"TARGETFLD='{escaped}'",
        outFields="WELLREGNO,TARGETFLD,ORIGINTENT,CURRWELLIN,DEVTYPE,COMPLESTAT,WELLOPSTAT,COMPLEDATE,SPUDDATE,TDMDDEPM,TDTVDSSM"))


def benchmark_wells():
    """No validated UK abandonment timeline: do not infer annual producing-well denominators."""
    return prepare_wells(pd.DataFrame())


@st.cache_data(ttl=86400, max_entries=128, show_spinner=False)
def load_geometry(name):
    escaped = str(name).replace("'", "''")
    features = query(FIELDS, where=f"FIELDNAME='{escaped}'", outFields="OBJECTID",
                     returnGeometry="true", outSR=4326)
    # Reuse the validated polygon/geodesic parser without confusing NSTA IDs with SODIR IDs.
    mapped = [dict(attributes={"fldNpdidField": 1}, geometry=feature.get("geometry")) for feature in features]
    try:
        return parse_field_geometry({"features": mapped}, 1)
    except ValueError as exc:
        raise DataUnavailable(f"NSTA field outline could not be read: {exc}") from exc


def namespace_ncs(master, yearly, wells):
    master, yearly, wells = master.copy(), yearly.copy(), wells.copy()
    master["field_name"] = master.index
    master["country"] = "NCS"
    master.index = "NCS::" + master.index.astype(str)
    yearly["prfInformationCarrier"] = "NCS::" + yearly["prfInformationCarrier"].astype(str)
    wells["wlbField"] = "NCS::" + wells["wlbField"].astype("string")
    return master, yearly, wells


def build_master(fields, yearly, current_year, start_threshold=0):
    from utils import benchmark as bm
    master = bm.build_master(fields, pd.DataFrame(), pd.DataFrame(), yearly, benchmark_wells(),
                             pd.DataFrame(), current_year=current_year, start_threshold=start_threshold)
    master["country"] = "UKCS"
    master["field_name"] = fields.set_index("fldName")["field_name"]
    master["production_basis"] = PRODUCTION_BASIS
    master["source"] = PRODUCTION
    return master
