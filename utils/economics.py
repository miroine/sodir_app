"""Field screening scenarios, including an explicitly restated current-regime tax model."""
from dataclasses import dataclass
from io import BytesIO
from math import isfinite

import numpy as np
import pandas as pd

from utils.investments import BOE_PER_SM3

PRODUCTS = ("oil", "gas", "condensate", "ngl")


def fitted_forecast(production, cutoff, years):
    history = validate_profile(production.loc[production["year"] <= cutoff])
    if history["year"].max() != cutoff:
        raise ValueError("Production must extend through the cutoff for decline fitting.")
    if not isinstance(years, int) or not 1 <= years <= 100:
        raise ValueError("Forecast horizon must be 1-100 whole years.")
    window = history.loc[history["year"] >= cutoff - 4]
    forecast = pd.DataFrame({"year": cutoff + np.arange(1, years + 1)})
    diagnostics = []
    for product in PRODUCTS:
        values = window[product]
        row = dict(product=product, first_year=int(window["year"].min()), last_year=cutoff,
                   observations=len(window), effective_decline_pct=None, r_squared=None,
                   fitted_cutoff_volume=0.0)
        if values.eq(0).all() or values.iloc[-1] == 0:
            forecast[product] = 0.0
            row["status"] = "No recent production" if values.eq(0).all() else "Zero at cutoff; no restart assumed"
        else:
            if len(window) < 3 or values.le(0).any():
                raise ValueError(f"{product}: need at least three positive consecutive annual observations "
                                 "within the last five years. Import a prognosis instead.")
            x = window["year"].to_numpy(dtype=float) - cutoff
            logged = np.log(values.to_numpy(dtype=float))
            slope, intercept = np.polyfit(x, logged, 1)
            if slope > 1e-10:
                raise ValueError(f"{product}: recent history is rising, not declining. "
                                 "A decline forecast is not justified; import a prognosis instead.")
            slope = min(float(slope), 0.0)
            fitted = intercept + slope * x
            total = float(np.sum((logged - logged.mean()) ** 2))
            row.update(status="Fitted exponential", effective_decline_pct=100 * (1 - np.exp(slope)),
                       fitted_cutoff_volume=float(np.exp(intercept)),
                       r_squared=1 - float(np.sum((logged - fitted) ** 2)) / total if total > 1e-20 else None)
            forecast[product] = np.exp(intercept + slope * (forecast["year"] - cutoff))
        diagnostics.append(row)
    if forecast[list(PRODUCTS)].to_numpy().sum() <= 0:
        raise ValueError("No producing product remains at the cutoff; import a prognosis for any restart.")
    return validate_profile(forecast), pd.DataFrame(diagnostics)


def recent_investment_average(investments, cutoff):
    window = investments.loc[investments["year"].between(cutoff - 4, cutoff), ["year", "nominal_mnok"]].copy()
    if window.empty:
        raise ValueError("No investment observations in the last five calendar years.")
    if window["year"].duplicated().any() or not np.isfinite(window["nominal_mnok"]).all():
        raise ValueError("Recent investment observations must be finite and unique by year.")
    missing = sorted(set(range(cutoff - 4, cutoff + 1)) - set(window["year"]))
    return float(window["nominal_mnok"].mean()), window.sort_values("year"), missing


@dataclass(frozen=True)
class TaxAssumptions:
    opening_ordinary_loss_mnok: float = 0.0

    def validate(self):
        if not isfinite(self.opening_ordinary_loss_mnok) or self.opening_ordinary_loss_mnok < 0:
            raise ValueError("Opening ordinary tax loss must be finite and non-negative.")


def current_regime_tax(data, assumptions):
    """Unlevered ring-fenced scenario; not actual company tax or historic legislation."""
    assumptions.validate()
    data = data.copy()
    # Complete the last six-year depreciation cohort and its next-year refund.
    final = int(data["year"].max())
    tail = pd.DataFrame(0.0, index=range(6), columns=data.select_dtypes(include="number").columns)
    tail["year"] = np.arange(final + 1, final + 7)
    tail["basis"] = "Tax settlement only"
    data = pd.concat([data, tail], ignore_index=True)
    data["ordinary_depreciation_mnok"] = data["investment_mnok"].rolling(6, min_periods=1).sum() / 6
    loss = assumptions.opening_ordinary_loss_mnok
    calculated_negative_tax = 0.22 * loss
    rows = []
    pending_refund = 0.0
    for row in data.itertuples():
        ordinary_base = row.operating_margin_mnok - row.ordinary_depreciation_mnok
        taxable = max(0.0, ordinary_base - loss)
        loss = max(0.0, loss - ordinary_base)
        ordinary_tax = 0.22 * taxable
        gross_calculated_tax = 0.22 * ordinary_base
        calculated_tax = max(0.0, gross_calculated_tax - calculated_negative_tax)
        calculated_negative_tax = max(0.0, calculated_negative_tax - gross_calculated_tax)
        special_base = row.operating_margin_mnok - row.investment_mnok - calculated_tax
        special_assessed = 0.718 * special_base
        special_paid = max(0.0, special_assessed)
        rows.append((ordinary_base, taxable, ordinary_tax, loss, calculated_tax, calculated_negative_tax,
                     special_base, special_assessed, special_paid, pending_refund))
        pending_refund = max(0.0, -special_assessed)
    columns = ["ordinary_tax_base_mnok", "ordinary_taxable_after_losses_mnok", "ordinary_tax_mnok",
               "ordinary_loss_closing_mnok", "calculated_ordinary_tax_mnok", "calculated_negative_tax_closing_mnok",
               "special_tax_base_mnok",
               "special_tax_assessed_mnok", "special_tax_paid_mnok", "special_refund_received_mnok"]
    data[columns] = pd.DataFrame(rows, index=data.index)
    data["tax_cash_mnok"] = data["ordinary_tax_mnok"] + data["special_tax_paid_mnok"] - data["special_refund_received_mnok"]
    data["after_tax_cash_flow_mnok"] = data["free_cash_flow_mnok"] - data["tax_cash_mnok"]
    if not np.isfinite(data[columns + ["after_tax_cash_flow_mnok", "ordinary_depreciation_mnok"]].to_numpy()).all():
        raise ValueError("Tax results exceed the supported numeric range.")
    return data


def cash_flow_irr(values):
    values = np.asarray(values, dtype=float)
    nonzero = values[values != 0]
    if len(nonzero) < 2 or not (np.any(nonzero < 0) and np.any(nonzero > 0)):
        return None, "No positive/negative cash-flow pair"
    if np.count_nonzero(np.diff(np.sign(nonzero))) != 1:
        return None, "Non-conventional cash flow: a unique IRR is not assured"
    periods = np.arange(len(values))

    def sign_value(rate):
        logs = -periods * np.log1p(rate)
        return float(np.sum(values * np.exp(logs - logs.max())))

    lo, hi = -0.9999, 1000.0
    left = sign_value(lo)
    if left * sign_value(hi) > 0:
        return None, "No IRR within -99.99% to 100,000%"
    for _ in range(120):
        mid = (lo + hi) / 2
        if sign_value(mid) * left > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2, "Unique conventional IRR"


def valuation(data, discount_rate, cutoff=None):
    part = data if cutoff is None else data.loc[data["year"] > cutoff]
    if part.empty:
        return dict(npv_mnok=None, after_tax_npv_mnok=None, irr=None, irr_status="No forward cash flows")
    periods = part["year"] - (int(data["year"].min()) - 1 if cutoff is None else cutoff)
    irr, status = cash_flow_irr(part["after_tax_cash_flow_mnok"])
    return dict(npv_mnok=float((part["free_cash_flow_mnok"] / (1 + discount_rate) ** periods).sum()),
                after_tax_npv_mnok=float((part["after_tax_cash_flow_mnok"] / (1 + discount_rate) ** periods).sum()),
                irr=irr, irr_status=status)


def break_even_oil(data, assumptions, tax, cutoff=None):
    def objective(price):
        scenario = data.loc[data["basis"].ne("Tax settlement only")].copy()
        mask = pd.Series(True, index=scenario.index) if cutoff is None else scenario["year"].gt(cutoff)
        revenue_change = scenario.loc[mask, "oil"] * BOE_PER_SM3 * assumptions.nok_per_usd * (price - assumptions.oil_usd_bbl)
        for column in ("revenue_mnok", "operating_margin_mnok", "free_cash_flow_mnok"):
            scenario.loc[mask, column] += revenue_change
        taxed = current_regime_tax(scenario, tax)
        part = taxed if cutoff is None else taxed.loc[taxed["year"] > cutoff]
        if part.empty:
            return None
        origin = int(taxed["year"].min()) - 1 if cutoff is None else cutoff
        return float((part["after_tax_cash_flow_mnok"] /
                      (1 + assumptions.discount_rate) ** (part["year"] - origin)).sum())

    relevant = data if cutoff is None else data.loc[data["year"] > cutoff]
    if relevant["oil"].sum() <= 0:
        return None, "No oil in this valuation period; oil-price break-even is undefined"
    low, high = objective(0), objective(10000)
    if low is None or high is None:
        return None, "No cash flows in valuation period"
    if low >= 0:
        return None, "Already non-negative NPV at zero oil price; no positive break-even required"
    if high < 0:
        return None, "No break-even found between 0 and 10,000 USD/bbl"
    lo, hi = 0.0, 10000.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if objective(mid) < 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2, "After-tax NPV zero; other product prices fixed"


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


def evaluate(history, forecast, assumptions, tax=None):
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
    if tax is not None:
        cutoff = int(history["year"].max())
        data = current_regime_tax(data, tax)
        data["cumulative_cash_flow_mnok"] = data["free_cash_flow_mnok"].cumsum()
        data["cumulative_discounted_mnok"] = data["discounted_cash_flow_mnok"].cumsum()
        periods = data["year"] - data["year"].min() + 1
        data["discounted_after_tax_mnok"] = data["after_tax_cash_flow_mnok"] / (1 + a.discount_rate) ** periods
        data["cumulative_after_tax_mnok"] = data["after_tax_cash_flow_mnok"].cumsum()
        data["cumulative_discounted_after_tax_mnok"] = data["discounted_after_tax_mnok"].cumsum()
        result["full_valuation"] = valuation(data, a.discount_rate)
        result["forward_valuation"] = valuation(data, a.discount_rate, cutoff)
        for key, valuation_cutoff in (("full_valuation", None), ("forward_valuation", cutoff)):
            price, status = break_even_oil(data, a, tax, valuation_cutoff)
            result[key].update(break_even_oil_usd_bbl=price, break_even_status=status)
    return data, result
