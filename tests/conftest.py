"""Offline NSTA boundary for app tests; dedicated adapter tests exercise transport separately."""
from unittest.mock import patch

import pandas as pd
import pytest

from utils import ukcs
from utils.data import YEARLY_COLUMNS


@pytest.fixture(autouse=True)
def nsta_offline_boundary():
    fields = pd.DataFrame([dict(
        fldName="UKCS::TEST UK", field_name="TEST UK", FIELDNAME="TEST UK", country="UKCS",
        fldHcType="OIL", FIELDTYPE="OIL", fldCurrentActivitySatus="PRODUCING", STATUS="PRODUCING",
        fldMainArea="UKCS", cmpLongName="UK Operator", CURR_OPER="UK Operator", DEPTH_M="100",
        DISC_WELL="1/1-1", OBJECTID=1,
    )])
    yearly = pd.DataFrame([
        dict(prfInformationCarrier="UKCS::TEST UK", prfYear=year,
             **{column: (float("nan") if "NGL" in column else 0.1) for column in YEARLY_COLUMNS},
             reporting_months=12, complete_reporting=True)
        for year in range(2021, 2025)
    ])
    with patch.object(ukcs, "load_fields", return_value=fields), patch.object(ukcs, "load_yearly", return_value=yearly):
        yield
