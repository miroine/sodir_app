from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from utils import portfolio as pf
from utils.data import DataUnavailable
from utils.investments import BOE_PER_SM3
from test_dashboard import ROOT, datasets


def equity_history():
    return pd.DataFrame([
        dict(fldName="OSEBERG", cmpLongName="Company A", cmpNpdidCompany=1, fldCompanyShare=60,
             fldOwnerFrom="01.01.2000", fldOwnerTo=None, fldLicenseeFrom="01.01.2020", fldLicenseeTo=None),
        dict(fldName="OSEBERG", cmpLongName="Company B", cmpNpdidCompany=2, fldCompanyShare=40,
             fldOwnerFrom="01.01.2000", fldOwnerTo=None, fldLicenseeFrom="01.01.2020", fldLicenseeTo=None),
        dict(fldName="OSEBERG", cmpLongName="Old Company", cmpNpdidCompany=3, fldCompanyShare=100,
             fldOwnerFrom="01.01.2000", fldOwnerTo=None, fldLicenseeFrom="01.01.2000", fldLicenseeTo="31.12.2019"),
    ])


def fields():
    return pd.DataFrame(dict(country=["NCS", "UKCS"], field_name=["A", "A"],
                             region=["North sea", "Central North Sea"],
                             production_basis=["SODIR", pf.ukcs.PRODUCTION_BASIS]),
                        index=pd.Index(["NCS::A", "UKCS::A"], name="fldName"))


def interests():
    return pd.DataFrame([
        dict(fldName=field, company=company, company_name=company, share=share, equity_source="test",
             snapshot_date="2026-10-30")
        for field, company, share in [("NCS::A", "NCS::1", .6), ("NCS::A", "NCS::2", .4),
                                      ("UKCS::A", "UKCS::LEGAL", .99)]
    ])


def test_snapshot_intersects_owner_and_licensee_dates():
    source = equity_history()
    result = pf.ncs_equity(source, "2026-10-30")
    assert set(result["company"]) == {"NCS::1", "NCS::2"}
    assert result["share"].sum() == 1
    old = pf.ncs_equity(source, "2019-12-31")
    assert old["company"].tolist() == ["NCS::3"]
    source.loc[0, "fldOwnerTo"] = "01.01.2025"
    assert "NCS::1" not in set(pf.ncs_equity(source, "2026-10-30")["company"])
    source.loc[0, "fldOwnerTo"] = "not a date"
    with pytest.raises(ValueError, match="invalid ownership dates"):
        pf.ncs_equity(source, "2026-10-30")


def test_uk_integer_equity_is_not_renormalised_and_same_field_names_are_distinct():
    features = [dict(attributes=dict(FIELDNAME="A", CURRLIC="LEGAL", EQUITY=97,
                                      CURRLIC2="OTHER", EQUITY2=2))]
    result = pf.uk_equity(features, "2026-10-30")
    equity, qa = pf.validate_equity(pd.concat([interests().iloc[:2], result]), fields())
    assert equity.loc[equity["fldName"].eq("UKCS::A"), "share"].sum() == .99
    assert qa.loc["UKCS::A", "unallocated_share_pct"] == pytest.approx(1)
    assert qa.loc["NCS::A", "unallocated_share_pct"] == 0
    for bad in [1.01, np.nan, -1]:
        invalid = interests()
        invalid.loc[0, "share"] = bad
        valid, audit = pf.validate_equity(invalid, fields())
        assert not valid["fldName"].eq("NCS::A").any()
        assert audit.loc["NCS::A", "allocated_share_pct"] == 0
    duplicate = pd.concat([interests(), interests().iloc[:1]])
    assert "Duplicate" in pf.validate_equity(duplicate, fields())[1].loc["NCS::A", "ownership_status"]


def test_region_polygon_holes_and_official_map_assignment():
    outer = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    hole = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]
    assert pf.point_in_rings((2, 2), [outer, hole])
    assert not pf.point_in_rings((5, 5), [outer, hole])
    feature = dict(attributes=dict(FIELDNAME="A"), centroid=dict(x=2, y=2))
    regions = [dict(attributes=dict(LINKTOPROD="https://test/UKCS_Oil_and_Gas_Activity_CNS.pdf"),
                    geometry=dict(rings=[outer]))]
    assert pf.uk_regions([feature], regions)["UKCS::A"] == "Central North Sea"
    assert "Unclassified" in pf.uk_regions([feature], regions * 2)["UKCS::A"]


def test_equity_conservation_and_matched_capex_ratio_of_sums():
    annual = pd.DataFrame([
        dict(fldName="NCS::A", year=2024, production_mboe=10., oil_mmbbl=5., nominal_mnok=100.),
        dict(fldName="NCS::A", year=2025, production_mboe=20., oil_mmbbl=10., nominal_mnok=300.),
        dict(fldName="NCS::A", year=2023, production_mboe=np.nan, oil_mmbbl=np.nan, nominal_mnok=50.),
        dict(fldName="UKCS::A", year=2024, production_mboe=100., oil_mmbbl=10., nominal_mnok=np.nan),
    ])
    ledger = pf.allocate(annual, interests())
    assert ledger.loc[ledger["fldName"].eq("NCS::A"), "nominal_mnok"].sum() == 450
    assert ledger.loc[ledger["fldName"].eq("UKCS::A"), "production_mboe"].sum() == 99
    grouped = pf.company_annual(ledger)
    summary = pf.company_summary(grouped).set_index("company")
    assert summary.loc["NCS::1", "nominal_mnok"] == 270
    assert summary.loc["NCS::1", "capex_nok_boe"] == pytest.approx(400 / 30)
    assert summary.loc["NCS::2", "capex_nok_boe"] == pytest.approx(400 / 30)
    assert pd.isna(summary.loc["UKCS::LEGAL", "nominal_mnok"])
    assert pd.isna(summary.loc["UKCS::LEGAL", "capex_nok_boe"])
    assert summary.loc["NCS::1", "capex_nok_boe"] != 12.5  # Not the mean of annual ratios.
    zeros = annual.iloc[:1].copy()
    zeros["production_mboe"] = 0
    result = pf.company_annual(pf.allocate(zeros, interests()))
    assert result["capex_nok_boe"].isna().all()
    assert result["matched_fields"].eq(1).all()
    assert result["matched_capex_mnok"].sum() == 100


def forecast_history():
    rows = []
    for country in ("NCS", "UKCS"):
        for year in range(2021, 2026):
            oil = .8 ** (year - 2021)
            rows.append(dict(fldName=f"{country}::A", year=year, oil=oil, gas=.1 * oil, condensate=.05 * oil,
                             ngl=0 if country == "NCS" else np.nan, oe=oil * 1.15,
                             production_mboe=oil * 1.15 * BOE_PER_SM3, nominal_mnok=20,
                             oil_mmbbl=oil * BOE_PER_SM3))
    return pd.DataFrame(rows)


def test_main_phase_fits_aggregate_to_equity_and_matched_index():
    history = forecast_history()
    future, audit = pf.forecast_fields(history, fields(), 2025, 2)
    assert audit["forecast_status"].eq("Included").all()
    first = future.loc[future["year"].eq(2026)].set_index("fldName")
    assert first.loc["NCS::A", "oil"] == pytest.approx(.8 ** 5)
    assert pd.isna(first.loc["UKCS::A", "ngl"])
    assert first.loc["UKCS::A", "oe"] == pytest.approx(.8 ** 5 * 1.15)
    company, ledger = pf.forecast_companies(future, history, interests(), 2025)
    assert company.loc[company["year"].eq(2026), "production_index"].tolist() == pytest.approx([80, 80, 80])
    assert company.loc[company["company"].eq("NCS::1") & company["year"].eq(2026), "production_mboe"].iloc[0] == pytest.approx(.6 * .8 ** 5 * 1.15 * BOE_PER_SM3)
    assert set(ledger["snapshot_date"]) == {"2026-10-30"}
    assert company["forecast_baseline_coverage_pct"].tolist() == pytest.approx([100] * 6)


def test_gapped_rising_and_stale_fields_are_excluded_not_zeroed():
    history = forecast_history()
    missing = history.loc[~(history["fldName"].eq("NCS::A") & history["year"].eq(2023))]
    future, audit = pf.forecast_fields(missing, fields(), 2025, 2)
    assert audit.loc["NCS::A", "forecast_status"] == "Excluded"
    assert set(future["fldName"]) == {"UKCS::A"}
    rising = history.copy()
    rising.loc[rising["fldName"].eq("NCS::A"), "oil"] = [1, 2, 3, 4, 5]
    assert "rising" in pf.forecast_fields(rising, fields(), 2025, 2)[1].loc["NCS::A", "forecast_detail"]
    assert pf.forecast_fields(history, fields(), 2026, 2)[0].empty


def test_upload_overrides_are_full_field_horizons_and_do_not_invent_ngl():
    upload = b"country,field,year,oil,gas,condensate,ngl\nNCS,A,2026,1,0,0,0\nNCS,A,2027,0,0,0,0\n"
    overrides = pf.parse_forecasts(upload, "input.csv", fields(), 2025, 2)
    future, audit = pf.forecast_fields(forecast_history(), fields(), 2025, 2, overrides)
    ncs = future.loc[future["fldName"].eq("NCS::A")]
    assert ncs["oil"].tolist() == [1, 0]
    assert audit.loc["NCS::A", "method"] == "Uploaded field forecast"
    for bad, message in [(upload.replace(b"2027", b"2028"), "every year"),
                         (upload.replace(b"NCS,A", b"NCS,UNKNOWN"), "Unknown"),
                         (upload.replace(b"2027", b"2026"), "unique whole"),
                         (upload.replace(b",1,0,0,0", b",-1,0,0,0"), "non-negative")]:
        with pytest.raises(ValueError, match=message):
            pf.parse_forecasts(bad, "input.csv", fields(), 2025, 2)
    with pytest.raises(ValueError, match="UK forecasts must leave ngl blank"):
        pf.parse_forecasts(upload.replace(b"NCS", b"UKCS"), "input.csv", fields(), 2025, 2)
    new_field = future.copy()
    company, _ = pf.forecast_companies(new_field, forecast_history().iloc[:0], interests(), 2025)
    assert company["production_index"].isna().all()


def test_portfolio_navigation_filters_company_equity_and_retained_forecast():
    tables = datasets()
    tables["equity"] = equity_history()
    tables["investments"] = pd.DataFrame(dict(prfInformationCarrier=["OSEBERG"] * 4,
                                               prfYear=[2021, 2022, 2023, 2024],
                                               prfInvestmentsMillNOK=[100., 200., 150., 50.]))
    with patch("utils.data.load_dataset", side_effect=lambda name: tables[name]):
        app = AppTest.from_file(str(ROOT / "app.py")).run()
        app.session_state["pf_countries"] = ["NCS"]
        app.sidebar.segmented_control(key="workspace").set_value("Portfolio").run()
        assert not app.exception
        assert not app.error
        assert any(title.value == "Portfolio" for title in app.title)
        app.multiselect(key="pf_companies").set_value(["NCS::1"]).run()
        assert not app.exception
        summary = app.dataframe[0].value
        assert summary["nominal_mnok"].sum() == 300
        app.number_input(key="pf_horizon").set_value(2).run()
        app.session_state["portfolio_upload"] = ("invalid.csv", b"country,field,year,oil,gas,condensate,ngl\nNCS,OSEBERG,2025,1,0,0,0\n")
        app.run()
        assert not app.exception
        assert any("no forecast is displayed" in message.value for message in app.error)
        assert not any("company forecast" in str(button.label).lower() for button in app.get("download_button"))
        app.session_state["portfolio_upload"] = ("input.csv", b"country,field,year,oil,gas,condensate,ngl\nNCS,OSEBERG,2025,1,0,0,0\nNCS,OSEBERG,2026,0.5,0,0,0\n")
        app.run()
        assert not app.exception
        assert not app.error
        assert any("method" in frame.value and frame.value["method"].eq("Uploaded field forecast").any()
                   for frame in app.dataframe)
        app.sidebar.segmented_control(key="workspace").set_value("Field Explorer").run()
        app.sidebar.selectbox(key="field").set_value("EMPTY").run()
        app.sidebar.segmented_control(key="workspace").set_value("Portfolio").run()
        assert not app.exception
        assert app.multiselect(key="pf_companies").value == ["NCS::1"]
        assert app.number_input(key="pf_horizon").value == 2
        assert "portfolio_upload" in app.session_state
        app.button(key="pf_clear_upload").click().run()
        assert not app.exception
        assert "portfolio_upload" not in app.session_state
        app.sidebar.segmented_control(key="workspace").set_value("Benchmark").run()
        assert not app.exception


def test_portfolio_can_open_despite_selected_field_database_outage():
    tables = datasets()
    tables["equity"] = equity_history()
    with patch("utils.data.load_dataset", side_effect=lambda name: tables[name]):
        app = AppTest.from_file(str(ROOT / "app.py")).run()
        app.session_state["pf_countries"] = ["NCS"]
        with patch("utils.ukcs.load_fields", side_effect=DataUnavailable("Test UK outage")):
            app.sidebar.segmented_control(key="workspace").set_value("Portfolio").run()
            app.sidebar.segmented_control(key="database").set_value("UKCS · NSTA").run()
            assert not app.exception
            assert not app.error
            assert any(title.value == "Portfolio" for title in app.title)
