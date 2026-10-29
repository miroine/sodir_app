"""Undiscounted/discounted pre-tax screening scenarios, not audited field economics."""
from dataclasses import dataclass
from io import BytesIO
from math import isfinite

import numpy as np
import pandas as pd

from utils.investments import BOE_PER_SM3

PRODUCTS = ("oil", "gas", "condensate", "ngl")


@dataclass(frozen=True)
class Assumptions:
    oil_usd_bbl: float = 70
    gas_usd_sm3: float = 0.30
    condensate_usd_bbl: float = 70
    ngl_usd_bbl: float = 40
    nok_per_usd: float = 10
    variable_opex_usd_boe: float = 12
    fixed_opex_mnok: float = 1000
    discount_rate: float = 0.08

    def validate(self):
        values = vars(self)
        if not all(isfinite(value) and value >= 0 for value in values.values()):
            raise ValueError("Economic assumptions must be finite and non-negative.")
        if self.nok_per_usd <= 0 or self.discount_rate > 1:
            raise ValueError("NOK/USD must be positive and the discount rate must be between 0 and 100%.")


def validate_profile(profile):
    profile = profile.copy()
    if profile.columns.duplicated().any():
        raise ValueError("Profile column names must be unique.")
    if "year" not in profile or profile.empty:
        raise ValueError("A non-empty annual profile with year is required.")
    if not any(product in profile for product in PRODUCTS):
        raise ValueError("Economics needs product volumes (oil/gas/condensate/ngl), not an oil-equivalent-only profile.")
    for product in PRODUCTS:
        if product not in profile:
            profile[product] = 0.0
        profile[product] = pd.to_numeric(profile[product], errors="coerce")
    profile["year"] = pd.to_numeric(profile["year"], errors="coerce")
    if not (profile["year"].between(1900, 2200) & profile["year"].mod(1).eq(0)).all():
        raise ValueError("Profile years must be whole calendar years between 1900 and 2200.")
    profile["year"] = profile["year"].astype(int)
    if profile["year"].duplicated().any():
        raise ValueError("The profile contains duplicate years.")
    for product in PRODUCTS:
        if not (profile[product].ge(0) & profile[product].lt(float("inf"))).all():
            raise ValueError(f"{product} volumes must be finite, non-negative and not blank.")
    profile = profile.sort_values("year").reset_index(drop=True)
    if len(profile) > 1 and not profile["year"].diff().iloc[1:].eq(1).all():
        raise ValueError("Profile years must be consecutive; missing years cannot be assumed zero.")
    profile["oe"] = profile["oil"] + profile["gas"] + profile["condensate"] + 1.9 * profile["ngl"]
    return profile


def parse_prognosis(content, filename):
    raw = BytesIO(content)
    profile = pd.read_excel(raw) if filename.lower().endswith(".xlsx") else pd.read_csv(raw)
    profile.columns = profile.columns.str.strip().str.lower()
    profile = validate_profile(profile)
    if "investment_mnok" in profile:
        amounts = pd.to_numeric(profile["investment_mnok"], errors="coerce")
        if not (amounts.notna() & amounts.abs().lt(float("inf"))).all():
            raise ValueError("Forecast investment_mnok must contain finite values for every year.")
        profile["investment_mnok"] = amounts
    return profile


def decline_forecast(last_year, decline, years):
    if not isfinite(decline) or not 0 <= decline < 1:
        raise ValueError("Annual effective decline must be at least zero and below 100%.")
    if not isinstance(years, int) or not 1 <= years <= 100:
        raise ValueError("Forecast horizon must be 1-100 whole years.")
    seed = validate_profile(pd.DataFrame([last_year]))
    if seed.iloc[0]["oe"] <= 0:
        raise ValueError("Decline extrapolation needs a positive final-year production rate.")
    offsets = np.arange(1, years + 1)
    forecast = pd.DataFrame({"year": int(seed.iloc[0]["year"]) + offsets})
    for product in PRODUCTS:
        forecast[product] = seed.iloc[0][product] * (1 - decline) ** offsets
    return validate_profile(forecast)


def historical_profile(production, investments, cutoff):
    production = validate_profile(production.loc[production["year"] <= cutoff])
    investments = investments.loc[investments["year"] <= cutoff]
    if investments.empty:
        raise ValueError("No historical investment is available; payback cannot be established.")
    first = min(int(investments["year"].min()), int(production["year"].min()))
    years = pd.Index(range(first, cutoff + 1), name="year")
    missing_cost = years.difference(investments["year"])
    if len(missing_cost):
        raise ValueError("Investment years are missing: " + ", ".join(map(str, missing_cost)) + ". Supply/verify a complete cost history before calculating payback.")
    if production["year"].max() != cutoff:
        raise ValueError("Production does not extend through the historical cutoff.")
    data = production.set_index("year").reindex(years)
    preproduction = data.index < production["year"].min()
    data.loc[preproduction, [*PRODUCTS, "oe"]] = 0.0
    data["investment_mnok"] = investments.set_index("year")["nominal_mnok"]
    return data.reset_index()


def evaluate(history, forecast, assumptions):
    assumptions.validate()
    history = validate_profile(history)
    history["basis"] = "Historical volumes / scenario prices"
    if not forecast.empty:
        forecast = validate_profile(forecast)
        if int(forecast["year"].min()) != int(history["year"].max()) + 1:
            raise ValueError("The prognosis must start the year immediately after the historical cutoff.")
        forecast["basis"] = "Forecast scenario"
    data = pd.concat([history, forecast], ignore_index=True)
    if "investment_mnok" not in data or data["investment_mnok"].isna().any():
        raise ValueError("Explicit investment assumptions are required for every historical and forecast year.")
    if not (data["investment_mnok"].abs().lt(float("inf"))).all():
        raise ValueError("Investment assumptions must be finite.")
    a = assumptions
    data["revenue_mnok"] = (
        (data["oil"] * a.oil_usd_bbl + data["condensate"] * a.condensate_usd_bbl
         + data["ngl"] * a.ngl_usd_bbl) * BOE_PER_SM3 + data["gas"] * 1000 * a.gas_usd_sm3
    ) * a.nok_per_usd
    data["opex_mnok"] = data["oe"] * BOE_PER_SM3 * a.variable_opex_usd_boe * a.nok_per_usd
    data["opex_mnok"] += np.where(data["oe"] > 0, a.fixed_opex_mnok, 0)
    data["operating_margin_mnok"] = data["revenue_mnok"] - data["opex_mnok"]
    data["free_cash_flow_mnok"] = data["operating_margin_mnok"] - data["investment_mnok"]
    data["cumulative_cash_flow_mnok"] = data["free_cash_flow_mnok"].cumsum()
    periods = data["year"] - data["year"].min() + 1
    data["discounted_cash_flow_mnok"] = data["free_cash_flow_mnok"] / (1 + a.discount_rate) ** periods
    data["cumulative_discounted_mnok"] = data["discounted_cash_flow_mnok"].cumsum()
    numeric = data[["revenue_mnok", "opex_mnok", "free_cash_flow_mnok", "discounted_cash_flow_mnok",
                    "cumulative_cash_flow_mnok", "cumulative_discounted_mnok"]]
    if not np.isfinite(numeric.to_numpy()).all():
        raise ValueError("Economic results exceed the supported numeric range.")
    result = {"first_year": int(data["year"].min()), "last_year": int(data["year"].max())}
    for key, column in (("payback_year", "cumulative_cash_flow_mnok"),
                        ("discounted_payback_year", "cumulative_discounted_mnok")):
        funded = data[column].lt(0).cummax().shift(fill_value=False)
        recovered = data.loc[funded & data[column].ge(0), "year"]
        result[key] = int(recovered.iloc[0]) if not recovered.empty else None
    future = data.loc[data["basis"].eq("Forecast scenario")]
    limit = future.loc[future["operating_margin_mnok"].le(0) | future["oe"].eq(0), "year"]
    result["economic_limit_year"] = int(limit.iloc[0]) if not limit.empty else None
    result["cessation_year"] = result["economic_limit_year"] - 1 if result["economic_limit_year"] else None
    result["npv_mnok"] = float(data["discounted_cash_flow_mnok"].sum())
    return data, result
