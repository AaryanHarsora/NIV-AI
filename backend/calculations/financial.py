"""
Deterministic financial calculations for Niv AI.
Every number that appears in a decision report originates from this file.
The LLM never performs arithmetic — it only interprets these results.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from backend.calculations.delta_engine import classify_financial_state, compute_survival_timeline


@dataclass
class EMIResult:
    monthly_emi: float
    total_payment: float
    total_interest: float
    loan_amount: float
    annual_rate: float
    tenure_months: int


@dataclass
class AcquisitionCost:
    property_price: float
    stamp_duty: float
    registration: float
    gst: float
    legal_fees: float
    brokerage: float
    total: float


@dataclass
class MonthlyOwnership:
    emi: float
    maintenance: float
    home_insurance: float
    total: float


@dataclass
class KeyRatios:
    emi_to_income: float
    total_housing_to_income: float
    down_payment_to_savings: float
    emergency_runway_months: float
    existing_obligations_to_income: float


@dataclass
class TaxBenefits:
    section_80c_annual: float
    section_24b_annual: float
    total_annual_saving: float
    effective_monthly_saving: float


@dataclass
class StressResult:
    name: str
    description: str
    can_survive: bool
    months_before_default: Optional[float]
    key_number: str
    new_emi: Optional[float] = None
    new_ratio: Optional[float] = None


@dataclass
class RentVsBuyResult:
    equivalent_rent: float
    monthly_ownership_cost: float
    premium_pct: float
    opportunity_cost_monthly: float
    true_monthly_premium: float
    break_even_years: float


@dataclass
class ComputedNumbers:
    emi: EMIResult
    acquisition: AcquisitionCost
    monthly_ownership: MonthlyOwnership
    ratios: KeyRatios
    tax_benefits: TaxBenefits
    stress_scenarios: list
    rent_vs_buy: RentVsBuyResult
    post_purchase_savings: float
    loan_amount: float
    down_payment: float = field(default=0.0)
    interiors_estimated_cost: float = field(default=0.0)
    true_total_acquisition_cost: float = field(default=0.0)
    down_payment_opportunity_cost_10yr: float = field(default=0.0)
    annual_commute_cost_estimate: float = field(default=0.0)
    maintenance_5yr_projected_cost: float = field(default=0.0)
    true_monthly_cost_after_all_factors: float = field(default=0.0)
    financial_state: str = field(default="")
    survival_timeline: dict = field(default_factory=dict)
    assumptions_made: list = field(default_factory=list)
    stability_score: dict = field(default_factory=dict)
    affordability_envelope: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "loan_amount": self.loan_amount,
            "monthly_emi": self.emi.monthly_emi,
            "total_loan_payment": self.emi.total_payment,
            "total_interest_paid": self.emi.total_interest,
            "total_acquisition_cost": self.acquisition.total,
            "stamp_duty": self.acquisition.stamp_duty,
            "registration": self.acquisition.registration,
            "gst": self.acquisition.gst,
            "monthly_ownership_cost": self.monthly_ownership.total,
            "monthly_maintenance": self.monthly_ownership.maintenance,
            "emi_to_income_ratio": self.ratios.emi_to_income,
            "total_housing_to_income_ratio": self.ratios.total_housing_to_income,
            "down_payment_to_savings_ratio": self.ratios.down_payment_to_savings,
            "emergency_runway_months": self.ratios.emergency_runway_months,
            "post_purchase_savings": self.post_purchase_savings,
            "annual_tax_saving": self.tax_benefits.total_annual_saving,
            "effective_monthly_cost_after_tax": round(
                self.monthly_ownership.total - self.tax_benefits.effective_monthly_saving, 2
            ),
            "rent_vs_buy_premium_pct": self.rent_vs_buy.premium_pct,
            "rent_vs_buy_break_even_years": self.rent_vs_buy.break_even_years,
            "interiors_estimated_cost": self.interiors_estimated_cost,
            "true_total_acquisition_cost": self.true_total_acquisition_cost,
            "down_payment_opportunity_cost_10yr": self.down_payment_opportunity_cost_10yr,
            "annual_commute_cost_estimate": self.annual_commute_cost_estimate,
            "maintenance_5yr_projected_cost": self.maintenance_5yr_projected_cost,
            "true_monthly_cost_after_all_factors": self.true_monthly_cost_after_all_factors,
            "down_payment": self.down_payment,
            "assumptions_made": self.assumptions_made,
            "stability_score": self.stability_score,
            "affordability_envelope": self.affordability_envelope,
            "financial_state": self.financial_state,
            "survival_timeline": self.survival_timeline,
        }


def calculate_emi(principal: float, annual_rate_pct: float, tenure_months: int) -> EMIResult:
    if principal <= 0:
        return EMIResult(0, 0, 0, 0, annual_rate_pct, tenure_months)
    r = annual_rate_pct / 12 / 100
    n = tenure_months
    if r == 0:
        emi = principal / n
    else:
        emi = principal * r * math.pow(1 + r, n) / (math.pow(1 + r, n) - 1)
    emi = round(emi, 2)
    total_payment = round(emi * n, 2)
    total_interest = round(total_payment - principal, 2)
    return EMIResult(monthly_emi=emi, total_payment=total_payment, total_interest=total_interest,
                     loan_amount=principal, annual_rate=annual_rate_pct, tenure_months=tenure_months)


def calculate_acquisition_cost(property_price: float, buyer_gender: str = "male",
                                is_ready_to_move: bool = True, has_broker: bool = False,
                                is_mumbai_metro: bool = True) -> AcquisitionCost:
    stamp_duty_rate = 0.05 if buyer_gender == "female" else 0.06
    stamp_duty = round(property_price * stamp_duty_rate, 2)
    registration = min(round(property_price * 0.01, 2), 30000.0)
    gst = round(property_price * 0.05, 2) if not is_ready_to_move else 0.0
    legal_fees = 40000.0
    brokerage = round(property_price * 0.01, 2) if has_broker else 0.0
    total = round(property_price + stamp_duty + registration + gst + legal_fees + brokerage, 2)
    return AcquisitionCost(property_price=property_price, stamp_duty=stamp_duty,
                           registration=registration, gst=gst, legal_fees=legal_fees,
                           brokerage=brokerage, total=total)


def calculate_monthly_ownership(emi: float, carpet_area_sqft: float,
                                 maintenance_per_sqft: float = 5.5,
                                 home_insurance_monthly: float = 500.0) -> MonthlyOwnership:
    maintenance = round(carpet_area_sqft * maintenance_per_sqft, 2)
    total = round(emi + maintenance + home_insurance_monthly, 2)
    return MonthlyOwnership(emi=emi, maintenance=maintenance, home_insurance=home_insurance_monthly, total=total)


def calculate_key_ratios(monthly_income: float, spouse_income: float, emi: float,
                          total_monthly_housing: float, existing_emis: float,
                          monthly_expenses: float, liquid_savings: float,
                          down_payment: float) -> KeyRatios:
    household_income = max(monthly_income + spouse_income, 1.0)
    emi_ratio = round(emi / household_income, 4)
    housing_ratio = round(total_monthly_housing / household_income, 4)
    dp_ratio = round(down_payment / liquid_savings, 4) if liquid_savings > 0 else 99.0
    post_purchase_savings = max(liquid_savings - down_payment, 0)
    monthly_burn = emi + monthly_expenses + existing_emis
    runway = round(post_purchase_savings / monthly_burn, 2) if monthly_burn > 0 else 0.0
    obligations_ratio = round((emi + existing_emis) / household_income, 4)
    return KeyRatios(emi_to_income=emi_ratio, total_housing_to_income=housing_ratio,
                     down_payment_to_savings=dp_ratio, emergency_runway_months=runway,
                     existing_obligations_to_income=obligations_ratio)


def calculate_tax_benefits(annual_principal_repayment: float, annual_interest_payment: float,
                            is_self_occupied: bool = True, marginal_tax_rate: float = 0.30,
                            existing_80c_used: float = 0.0) -> TaxBenefits:
    available_80c = max(150000.0 - existing_80c_used, 0.0)
    sec_80c = min(annual_principal_repayment, available_80c)
    sec_24b = min(annual_interest_payment, 200000.0) if is_self_occupied else annual_interest_payment
    total_deduction = sec_80c + sec_24b
    annual_saving = round(total_deduction * marginal_tax_rate, 2)
    monthly_saving = round(annual_saving / 12, 2)
    return TaxBenefits(section_80c_annual=round(sec_80c, 2), section_24b_annual=round(sec_24b, 2),
                       total_annual_saving=annual_saving, effective_monthly_saving=monthly_saving)


def estimate_annual_principal_and_interest(loan_amount: float, annual_rate_pct: float,
                                            tenure_months: int) -> tuple:
    r = annual_rate_pct / 12 / 100
    if r == 0 or loan_amount <= 0:
        return (loan_amount / max(tenure_months, 1) * 12, 0.0)
    emi = loan_amount * r * math.pow(1 + r, tenure_months) / (math.pow(1 + r, tenure_months) - 1)
    annual_interest = 0.0
    annual_principal = 0.0
    balance = loan_amount
    for _ in range(min(12, tenure_months)):
        interest_component = balance * r
        principal_component = emi - interest_component
        annual_interest += interest_component
        annual_principal += principal_component
        balance -= principal_component
    return (round(annual_principal, 2), round(annual_interest, 2))


def calculate_stress_scenarios(monthly_income: float, spouse_income: float, emi: float,
                                total_monthly_expenses: float, existing_emis: float,
                                post_purchase_savings: float, loan_amount: float,
                                annual_rate_pct: float, tenure_months: int) -> list:
    household_income = monthly_income + spouse_income
    monthly_burn = emi + total_monthly_expenses + existing_emis
    runway_job_loss = round(post_purchase_savings / monthly_burn, 1) if monthly_burn > 0 else 0
    job_loss = StressResult(name="job_loss_6_months",
                            description="Primary earner loses income for 6 months",
                            can_survive=runway_job_loss >= 6,
                            months_before_default=runway_job_loss,
                            key_number=f"Savings last {runway_job_loss} months (need 6)")

    new_rate = annual_rate_pct + 2.0
    new_emi_result = calculate_emi(loan_amount, new_rate, tenure_months)
    new_emi = new_emi_result.monthly_emi
    emi_increase_pct = round((new_emi - emi) / emi * 100, 1) if emi > 0 else 0
    new_ratio = round(new_emi / household_income, 4) if household_income > 0 else 99
    rate_hike = StressResult(name="interest_rate_hike_2pct",
                             description="Interest rate increases by 2 percentage points",
                             can_survive=new_ratio < 0.50,
                             months_before_default=None,
                             key_number=f"EMI rises {emi_increase_pct}% to Rs.{new_emi:,.0f}",
                             new_emi=new_emi, new_ratio=new_ratio)

    savings_after_shock = post_purchase_savings - 500000
    runway_after_shock = round(savings_after_shock / monthly_burn, 1) if monthly_burn > 0 and savings_after_shock > 0 else 0
    expense_shock = StressResult(name="unexpected_expense_5L",
                                 description="Major emergency requiring Rs.5,00,000",
                                 can_survive=savings_after_shock > 0 and runway_after_shock >= 3,
                                 months_before_default=max(runway_after_shock, 0),
                                 key_number=f"Remaining savings: Rs.{max(savings_after_shock, 0):,.0f}")

    real_income_year3 = household_income * math.pow(0.94, 3)
    year3_ratio = round(emi / real_income_year3, 4) if real_income_year3 > 0 else 99
    decline_pct = round((1 - real_income_year3 / household_income) * 100, 1)
    stagnation = StressResult(name="income_stagnation_3_years",
                              description="No salary increase for 3 years with 6% inflation",
                              can_survive=year3_ratio < 0.50,
                              months_before_default=None,
                              key_number=f"Real income drops {decline_pct}%, EMI-to-income becomes {year3_ratio:.0%}",
                              new_ratio=year3_ratio)

    return [job_loss, rate_hike, expense_shock, stagnation]


def calculate_rent_vs_buy(equivalent_monthly_rent: float, total_monthly_ownership: float,
                           down_payment: float, fd_return_pct: float = 7.0,
                           appreciation_pct: float = 4.0) -> RentVsBuyResult:
    opportunity_cost = round(down_payment * (fd_return_pct / 100) / 12, 2)
    premium_pct = round((total_monthly_ownership - equivalent_monthly_rent) / equivalent_monthly_rent * 100, 1) if equivalent_monthly_rent > 0 else 0
    true_premium = round(total_monthly_ownership + opportunity_cost - equivalent_monthly_rent, 2)
    annual_ownership_extra = true_premium * 12
    if annual_ownership_extra <= 0:
        break_even = 0.0
    elif appreciation_pct > 0:
        annual_appreciation_value = down_payment * (appreciation_pct / 100)
        break_even = round(annual_ownership_extra / annual_appreciation_value, 1) if annual_appreciation_value > 0 else 99.0
    else:
        break_even = 99.0
    return RentVsBuyResult(equivalent_rent=equivalent_monthly_rent, monthly_ownership_cost=total_monthly_ownership,
                           premium_pct=premium_pct, opportunity_cost_monthly=opportunity_cost,
                           true_monthly_premium=true_premium, break_even_years=min(break_even, 99.0))


def normalize_inputs(raw: dict) -> tuple[dict, list[str]]:
    """
    Normalizes and validates raw input before computation.
    Returns (cleaned_dict, list_of_assumptions_made).

    Rules:
    - monthly_expenses: if 0 or missing, default to 40% of income,
      flag as assumption
    - existing_emis: if negative, set to 0
    - liquid_savings: if > property_price * 5, flag as unusually high
    - down_payment: if < property_price * 0.20, flag minimum RBI requirement
    - interest_rate: if < 6.5 or > 15, flag as outside normal range
    - carpet_area_sqft: if < 100 or > 10000, flag as unusual
    - spouse_income: if negative, set to 0
    - dependents: if > 10, cap at 10 with flag

    Each assumption made is appended to the list as a plain English string.
    Returns the cleaned dict and the assumptions list.
    These assumptions flow into confidence_score calculation.
    """
    cleaned = dict(raw)
    assumptions: list[str] = []

    monthly_income = float(cleaned.get('monthly_income') or 0)
    spouse_income = float(cleaned.get('spouse_income') or 0)
    total_income = monthly_income + spouse_income

    # spouse_income: if negative, set to 0
    if spouse_income < 0:
        cleaned['spouse_income'] = 0.0
        assumptions.append("Spouse income was negative; reset to 0")
        spouse_income = 0.0
        total_income = monthly_income

    # monthly_expenses: if 0 or missing, default to 40% of income
    monthly_expenses = float(cleaned.get('monthly_expenses') or 0)
    if monthly_expenses == 0:
        defaulted = round(total_income * 0.40, 2)
        cleaned['monthly_expenses'] = defaulted
        assumptions.append(
            f"Monthly expenses not provided; defaulted to 40% of household income "
            f"(Rs.{defaulted:,.0f})"
        )

    # existing_emis: if negative, set to 0
    existing_emis = float(cleaned.get('existing_emis') or 0)
    if existing_emis < 0:
        cleaned['existing_emis'] = 0.0
        assumptions.append("Existing EMIs were negative; reset to 0")

    property_price = float(cleaned.get('property_price') or 0)

    # liquid_savings: if > property_price * 5, flag as unusually high
    liquid_savings = float(cleaned.get('liquid_savings') or 0)
    if property_price > 0 and liquid_savings > property_price * 5:
        assumptions.append(
            f"Liquid savings (Rs.{liquid_savings:,.0f}) are unusually high — more than 5x "
            f"the property price (Rs.{property_price:,.0f}); verify this is correct"
        )

    # down_payment: if < property_price * 0.20, flag minimum RBI requirement
    down_payment = float(cleaned.get('down_payment') or 0)
    if property_price > 0 and down_payment < property_price * 0.20:
        min_required = round(property_price * 0.20, 2)
        assumptions.append(
            f"Down payment (Rs.{down_payment:,.0f}) is below RBI's minimum 20% requirement "
            f"(Rs.{min_required:,.0f})"
        )

    # interest_rate: if < 6.5 or > 15, flag as outside normal range
    interest_rate = float(cleaned.get('interest_rate') or 0)
    if interest_rate > 0 and (interest_rate < 6.5 or interest_rate > 15):
        assumptions.append(
            f"Interest rate ({interest_rate}%) is outside the normal Indian home loan range "
            f"(6.5–15%); verify this is the correct rate"
        )

    # carpet_area_sqft: if < 100 or > 10000, flag as unusual
    carpet_area = float(cleaned.get('carpet_area_sqft') or 0)
    if carpet_area > 0 and (carpet_area < 100 or carpet_area > 10000):
        assumptions.append(
            f"Carpet area ({carpet_area:,.0f} sqft) is outside the typical residential range "
            f"(100–10,000 sqft); verify the unit is correct"
        )

    # dependents: if > 10, cap at 10 with flag
    dependents = int(cleaned.get('dependents') or 0)
    if dependents > 10:
        cleaned['dependents'] = 10
        assumptions.append(
            f"Dependents count ({dependents}) exceeds the maximum modelled value; capped at 10"
        )

    return cleaned, assumptions


def compute_confidence_score(
    raw_input: dict,
    assumptions_made: list[str],
    benchmark_coverage: str
) -> dict:
    """
    Scores analysis confidence 1-10 based on data completeness.

    Deductions from base score of 10:
    - monthly_expenses missing/defaulted: -1.5
    - no builder_name provided: -0.5
    - no carpet_area_sqft (using default): -1.0
    - benchmark_coverage == 'default': -2.0
    - benchmark_coverage == 'partial': -1.0
    - possession_date missing for under-construction: -1.0
    - each assumption_made beyond 2: -0.3 each
    - employment_type == 'freelance' or 'business': -0.5
      (income less predictable)

    Returns dict with:
    - score: float (1-10, rounded to 1 decimal)
    - label: "High" | "Medium" | "Low"
    - reasons: list of strings explaining deductions
    - data_completeness_pct: int (0-100)
    """
    score = 10.0
    reasons: list[str] = []

    # monthly_expenses missing/defaulted
    if not raw_input.get('monthly_expenses'):
        score -= 1.5
        reasons.append("Monthly expenses not provided (defaulted to 40% of income): -1.5")

    # no builder_name
    if not raw_input.get('builder_name'):
        score -= 0.5
        reasons.append("Builder name not provided: -0.5")

    # no carpet_area_sqft
    if not raw_input.get('carpet_area_sqft'):
        score -= 1.0
        reasons.append("Carpet area not provided (using default): -1.0")

    # benchmark_coverage
    if benchmark_coverage == 'default':
        score -= 2.0
        reasons.append("Benchmark data using defaults — no local comparables available: -2.0")
    elif benchmark_coverage == 'partial':
        score -= 1.0
        reasons.append("Benchmark data only partially available: -1.0")

    # possession_date missing for under-construction
    is_ready_to_move = raw_input.get('is_ready_to_move', True)
    if not is_ready_to_move and not raw_input.get('possession_date'):
        score -= 1.0
        reasons.append(
            "Possession date missing for under-construction property: -1.0"
        )

    # each assumption beyond 2
    extra = max(len(assumptions_made) - 2, 0)
    if extra > 0:
        deduction = round(extra * 0.3, 1)
        score -= deduction
        reasons.append(
            f"{extra} additional assumption(s) required beyond normal threshold: -{deduction}"
        )

    # employment_type unpredictable income
    employment_type = str(raw_input.get('employment_type') or '').lower()
    if employment_type in ('freelance', 'business'):
        score -= 0.5
        reasons.append(
            f"Employment type is '{employment_type}' — income less predictable than salaried: -0.5"
        )

    score = max(round(score, 1), 1.0)

    if score >= 7.0:
        label = "High"
    elif score >= 4.0:
        label = "Medium"
    else:
        label = "Low"

    key_fields = [
        'monthly_income', 'monthly_expenses', 'liquid_savings', 'property_price',
        'down_payment', 'interest_rate', 'carpet_area_sqft', 'builder_name',
        'employment_type', 'loan_tenure_years',
    ]
    present = sum(1 for f in key_fields if raw_input.get(f))
    data_completeness_pct = int(present / len(key_fields) * 100)

    return {
        'score': score,
        'label': label,
        'reasons': reasons,
        'data_completeness_pct': data_completeness_pct,
    }


def compute_stability_score(
    base_computed: dict,
    monthly_income: float,
    property_price: float,
    down_payment: float,
    interest_rate: float,
    loan_tenure_years: int,
    **kwargs
) -> dict:
    """
    Tests how sensitive the verdict is to small input changes.
    Flags if tiny changes flip the outcome significantly.

    Tests:
    1. Income -10%: recompute EMI ratio. If ratio crosses 30% or 45%
       threshold, flag as "income-sensitive"
    2. Rate +1%: recompute EMI. If crosses threshold, flag as
       "rate-sensitive"
    3. Property price +5%: recompute. Flag if changes verdict zone.

    Returns dict with:
    - is_stable: bool
    - income_sensitivity: "low" | "medium" | "high"
    - rate_sensitivity: "low" | "medium" | "high"
    - price_sensitivity: "low" | "medium" | "high"
    - stability_label: "Stable" | "Strained" | "Fragile" | "Critical"
    - tipping_points: list of strings describing exact thresholds
      e.g. "A 10% income drop would push EMI ratio from 28% to 31%,
      crossing the 'stretched' threshold"
    """
    spouse_income = float(kwargs.get('spouse_income') or 0)
    household_income = max(monthly_income + spouse_income, 1.0)
    loan_amount = max(property_price - down_payment, 0.0)
    tenure_months = loan_tenure_years * 12

    base_emi: float = base_computed.get('monthly_emi', 0.0)
    base_ratio: float = base_computed.get('emi_to_income_ratio', 0.0)

    tipping_points: list[str] = []

    # Test 1: Income -10%
    reduced_income = household_income * 0.90
    income_ratio = round(base_emi / reduced_income, 4) if reduced_income > 0 else 99.0
    if base_ratio < 0.45 <= income_ratio:
        income_sensitivity = "high"
        tipping_points.append(
            f"A 10% income drop would push EMI ratio from {base_ratio:.0%} to {income_ratio:.0%}, "
            f"crossing the 'danger' threshold (45%)"
        )
    elif base_ratio < 0.30 <= income_ratio:
        income_sensitivity = "medium"
        tipping_points.append(
            f"A 10% income drop would push EMI ratio from {base_ratio:.0%} to {income_ratio:.0%}, "
            f"crossing the 'stretched' threshold (30%)"
        )
    else:
        income_sensitivity = "low"

    # Test 2: Rate +1%
    new_emi = calculate_emi(loan_amount, interest_rate + 1.0, tenure_months).monthly_emi
    rate_ratio = round(new_emi / household_income, 4) if household_income > 0 else 99.0
    if base_ratio < 0.45 <= rate_ratio:
        rate_sensitivity = "high"
        tipping_points.append(
            f"A 1% rate increase would raise EMI from Rs.{base_emi:,.0f} to Rs.{new_emi:,.0f}, "
            f"pushing ratio from {base_ratio:.0%} to {rate_ratio:.0%} — crossing the 'danger' threshold (45%)"
        )
    elif base_ratio < 0.30 <= rate_ratio:
        rate_sensitivity = "medium"
        tipping_points.append(
            f"A 1% rate increase would raise EMI from Rs.{base_emi:,.0f} to Rs.{new_emi:,.0f}, "
            f"pushing ratio from {base_ratio:.0%} to {rate_ratio:.0%} — crossing the 'stretched' threshold (30%)"
        )
    else:
        rate_sensitivity = "low"

    # Test 3: Property price +5%
    new_loan = max(property_price * 1.05 - down_payment, 0.0)
    price_emi = calculate_emi(new_loan, interest_rate, tenure_months).monthly_emi
    price_ratio = round(price_emi / household_income, 4) if household_income > 0 else 99.0
    if base_ratio < 0.45 <= price_ratio:
        price_sensitivity = "high"
        tipping_points.append(
            f"A 5% property price increase would push EMI ratio from {base_ratio:.0%} to {price_ratio:.0%}, "
            f"crossing the 'danger' threshold (45%)"
        )
    elif base_ratio < 0.30 <= price_ratio:
        price_sensitivity = "medium"
        tipping_points.append(
            f"A 5% property price increase would push EMI ratio from {base_ratio:.0%} to {price_ratio:.0%}, "
            f"crossing the 'stretched' threshold (30%)"
        )
    else:
        price_sensitivity = "low"

    sensitivities = [income_sensitivity, rate_sensitivity, price_sensitivity]
    high_count = sensitivities.count("high")
    medium_count = sensitivities.count("medium")

    if high_count >= 2 or base_ratio >= 0.45:
        stability_label = "Critical"
    elif high_count == 1:
        stability_label = "Fragile"
    elif medium_count >= 1:
        stability_label = "Strained"
    else:
        stability_label = "Stable"

    return {
        'is_stable': stability_label == "Stable",
        'income_sensitivity': income_sensitivity,
        'rate_sensitivity': rate_sensitivity,
        'price_sensitivity': price_sensitivity,
        'stability_label': stability_label,
        'tipping_points': tipping_points,
    }


def compute_affordability_envelope(
    monthly_income: float,
    spouse_income: float,
    existing_emis: float,
    monthly_expenses: float,
    liquid_savings: float,
    interest_rate: float,
    loan_tenure_years: int,
    **kwargs
) -> dict:
    """
    Calculates the SAFE range for property price and down payment.

    Safe max property price: binary search for price where
      EMI/income < 0.30 AND runway > 6 months
    Stretch max property price: binary search for price where
      EMI/income < 0.45 AND runway > 3 months
    Min down payment for safe: binary search for down_payment where
      same criteria met at current property_price

    Returns dict with:
    - safe_max_price: float
    - stretch_max_price: float
    - min_down_for_safe: float
    - current_vs_safe_pct: float (how far current price is from safe max)
    - envelope_label: "Within safe range" | "Slightly above" |
                      "Well above" | "Dangerously above"
    """
    property_price = float(kwargs.get('property_price') or 0)
    down_payment = float(kwargs.get('down_payment') or 0)
    household_income = max(monthly_income + spouse_income, 1.0)
    tenure_months = loan_tenure_years * 12

    def _metrics(price: float, dp: float) -> tuple[float, float]:
        loan = max(price - dp, 0.0)
        emi = calculate_emi(loan, interest_rate, tenure_months).monthly_emi
        ratio = emi / household_income
        post_savings = max(liquid_savings - dp, 0.0)
        burn = emi + monthly_expenses + existing_emis
        runway = post_savings / burn if burn > 0 else 0.0
        return ratio, runway

    def _safe(price: float, dp: float) -> bool:
        ratio, runway = _metrics(price, dp)
        return ratio < 0.30 and runway > 6

    def _stretch(price: float, dp: float) -> bool:
        ratio, runway = _metrics(price, dp)
        return ratio < 0.45 and runway > 3

    # Binary search: safe_max_price (down payment held fixed)
    lo, hi = 0.0, household_income * 300.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if _safe(mid, down_payment):
            lo = mid
        else:
            hi = mid
    safe_max_price = round(lo, -3)

    # Binary search: stretch_max_price
    lo, hi = 0.0, household_income * 500.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if _stretch(mid, down_payment):
            lo = mid
        else:
            hi = mid
    stretch_max_price = round(lo, -3)

    # Binary search: min_down_for_safe at current property_price
    if property_price > 0:
        lo, hi = 0.0, min(liquid_savings, property_price)
        for _ in range(50):
            mid = (lo + hi) / 2
            if _safe(property_price, mid):
                hi = mid  # this dp works; try smaller
            else:
                lo = mid  # need more dp
        min_down_for_safe = round(hi, -3)
    else:
        min_down_for_safe = 0.0

    # How far is the current price above the safe max
    if safe_max_price > 0 and property_price > 0:
        current_vs_safe_pct = round((property_price - safe_max_price) / safe_max_price * 100, 1)
    else:
        current_vs_safe_pct = 0.0

    if current_vs_safe_pct <= 0:
        envelope_label = "Within safe range"
    elif current_vs_safe_pct <= 20:
        envelope_label = "Slightly above"
    elif current_vs_safe_pct <= 50:
        envelope_label = "Well above"
    else:
        envelope_label = "Dangerously above"

    return {
        'safe_max_price': safe_max_price,
        'stretch_max_price': stretch_max_price,
        'min_down_for_safe': min_down_for_safe,
        'current_vs_safe_pct': current_vs_safe_pct,
        'envelope_label': envelope_label,
    }


def compute_all(monthly_income: float, spouse_income: float, existing_emis: float,
                monthly_expenses: float, liquid_savings: float, dependents: int,
                property_price: float, down_payment: float, loan_tenure_years: int,
                interest_rate: float, carpet_area_sqft: float, buyer_gender: str,
                is_ready_to_move: bool, maintenance_per_sqft: float = 5.5,
                equivalent_rent: float = 0.0, commute_distance_km: float = 0.0,
                **kwargs) -> ComputedNumbers:
    """
    Master financial computation function. Runs all deterministic calculations for a home-buying decision.

    Args:
        monthly_income: Primary earner's gross monthly income in INR.
        spouse_income: Co-borrower/spouse gross monthly income in INR.
        existing_emis: Sum of all existing monthly loan obligations in INR.
        monthly_expenses: Monthly household living expenses in INR.
        liquid_savings: Total liquid savings available (cash, FD, liquid mutual funds) in INR.
        dependents: Number of financial dependents.
        property_price: Total property price in INR.
        down_payment: Amount available as down payment in INR.
        loan_tenure_years: Desired loan repayment tenure in years.
        interest_rate: Expected annual interest rate as a percentage.
        carpet_area_sqft: Property carpet area in square feet.
        buyer_gender: "male" or "female" — affects stamp duty rate.
        is_ready_to_move: True for ready-to-move, False for under-construction (affects GST).
        maintenance_per_sqft: Monthly maintenance charge per sqft. Defaults to 5.5.
        equivalent_rent: Market rent for a comparable property. Defaults to 2.5% yield estimate.
        commute_distance_km: One-way commute distance to office in km. Defaults to 0 (not provided).
        **kwargs: Extra fields (builder_name, employment_type, possession_date, etc.) passed
            through to normalize_inputs and downstream enrichment layers.

    Returns:
        ComputedNumbers dataclass containing all computed financial metrics.
    """
    # Build raw dict and normalize inputs
    raw = {
        'monthly_income': monthly_income,
        'spouse_income': spouse_income,
        'existing_emis': existing_emis,
        'monthly_expenses': monthly_expenses,
        'liquid_savings': liquid_savings,
        'dependents': dependents,
        'property_price': property_price,
        'down_payment': down_payment,
        'loan_tenure_years': loan_tenure_years,
        'interest_rate': interest_rate,
        'carpet_area_sqft': carpet_area_sqft,
        'buyer_gender': buyer_gender,
        'is_ready_to_move': is_ready_to_move,
        **kwargs,
    }
    cleaned, assumptions_made = normalize_inputs(raw)

    # Re-bind from cleaned (normalization may have adjusted values)
    monthly_income = float(cleaned.get('monthly_income', monthly_income))
    spouse_income = float(cleaned.get('spouse_income', spouse_income))
    existing_emis = float(cleaned.get('existing_emis', existing_emis))
    monthly_expenses = float(cleaned.get('monthly_expenses', monthly_expenses))
    liquid_savings = float(cleaned.get('liquid_savings', liquid_savings))
    dependents = int(cleaned.get('dependents', dependents))
    property_price = float(cleaned.get('property_price', property_price))
    down_payment = float(cleaned.get('down_payment', down_payment))
    loan_tenure_years = int(cleaned.get('loan_tenure_years', loan_tenure_years))
    interest_rate = float(cleaned.get('interest_rate', interest_rate))
    carpet_area_sqft = float(cleaned.get('carpet_area_sqft', carpet_area_sqft))
    buyer_gender = cleaned.get('buyer_gender', buyer_gender)
    is_ready_to_move = cleaned.get('is_ready_to_move', is_ready_to_move)

    loan_amount = max(property_price - down_payment, 0)
    tenure_months = loan_tenure_years * 12
    emi = calculate_emi(loan_amount, interest_rate, tenure_months)
    acquisition = calculate_acquisition_cost(property_price=property_price, buyer_gender=buyer_gender,
                                             is_ready_to_move=is_ready_to_move)
    monthly_own = calculate_monthly_ownership(emi=emi.monthly_emi, carpet_area_sqft=carpet_area_sqft,
                                              maintenance_per_sqft=maintenance_per_sqft)
    ratios = calculate_key_ratios(monthly_income=monthly_income, spouse_income=spouse_income,
                                  emi=emi.monthly_emi, total_monthly_housing=monthly_own.total,
                                  existing_emis=existing_emis, monthly_expenses=monthly_expenses,
                                  liquid_savings=liquid_savings, down_payment=down_payment)
    annual_principal, annual_interest = estimate_annual_principal_and_interest(loan_amount, interest_rate, tenure_months)
    tax = calculate_tax_benefits(annual_principal_repayment=annual_principal, annual_interest_payment=annual_interest)
    post_purchase_savings = max(liquid_savings - down_payment, 0)
    stress = calculate_stress_scenarios(monthly_income=monthly_income, spouse_income=spouse_income,
                                        emi=emi.monthly_emi, total_monthly_expenses=monthly_expenses,
                                        existing_emis=existing_emis, post_purchase_savings=post_purchase_savings,
                                        loan_amount=loan_amount, annual_rate_pct=interest_rate, tenure_months=tenure_months)
    if equivalent_rent <= 0:
        equivalent_rent = round(property_price * 0.025 / 12, 2)
    rvb = calculate_rent_vs_buy(equivalent_monthly_rent=equivalent_rent, total_monthly_ownership=monthly_own.total,
                                down_payment=down_payment)

    # Hidden costs (Task 1.6)
    interiors = round(property_price * 0.12, 2)
    true_acquisition = round(acquisition.total + interiors, 2)
    dp_opportunity_10yr = round(down_payment * ((1.12 ** 10) - 1), 2)
    commute_annual = round(commute_distance_km * 2 * 8 * 250, 2) if commute_distance_km > 0 else 0.0
    maintenance_5yr = round(sum(monthly_own.maintenance * 12 * (1.15 ** yr) for yr in range(1, 6)), 2)
    true_monthly = round(
        monthly_own.total
        + (commute_annual / 12)
        + (maintenance_5yr / 60)
        - tax.effective_monthly_saving,
        2,
    )

    # Financial state classification and survival timeline
    _metrics_for_state = {
        'emi_to_income_ratio': ratios.emi_to_income,
        'emergency_runway_months': ratios.emergency_runway_months,
        'down_payment_to_savings_ratio': ratios.down_payment_to_savings,
    }
    fin_state = classify_financial_state(_metrics_for_state)
    survival = compute_survival_timeline(
        monthly_income=monthly_income,
        monthly_burn=emi.monthly_emi + monthly_expenses + existing_emis,
        liquid_savings=liquid_savings,
        post_purchase_savings=post_purchase_savings,
        monthly_emi=emi.monthly_emi,
    )

    # Stability and affordability layers
    base_dict = {
        'monthly_emi': emi.monthly_emi,
        'emi_to_income_ratio': ratios.emi_to_income,
    }
    stability = compute_stability_score(
        base_computed=base_dict,
        monthly_income=monthly_income,
        property_price=property_price,
        down_payment=down_payment,
        interest_rate=interest_rate,
        loan_tenure_years=loan_tenure_years,
        spouse_income=spouse_income,
    )
    envelope = compute_affordability_envelope(
        monthly_income=monthly_income,
        spouse_income=spouse_income,
        existing_emis=existing_emis,
        monthly_expenses=monthly_expenses,
        liquid_savings=liquid_savings,
        interest_rate=interest_rate,
        loan_tenure_years=loan_tenure_years,
        property_price=property_price,
        down_payment=down_payment,
    )

    return ComputedNumbers(
        emi=emi, acquisition=acquisition, monthly_ownership=monthly_own, ratios=ratios,
        tax_benefits=tax, stress_scenarios=stress, rent_vs_buy=rvb,
        post_purchase_savings=post_purchase_savings, loan_amount=loan_amount,
        down_payment=down_payment,
        interiors_estimated_cost=interiors,
        true_total_acquisition_cost=true_acquisition,
        down_payment_opportunity_cost_10yr=dp_opportunity_10yr,
        annual_commute_cost_estimate=commute_annual,
        maintenance_5yr_projected_cost=maintenance_5yr,
        true_monthly_cost_after_all_factors=true_monthly,
        assumptions_made=assumptions_made,
        stability_score=stability,
        affordability_envelope=envelope,
        financial_state=fin_state,
        survival_timeline=survival,
    )


def find_path_to_safe(base_params: dict, current_verdict: str, max_search_steps: int = 40) -> dict | None:
    """
    Determines the minimum financial changes required to achieve a SAFE verdict.

    Uses linear search over down_payment increments and property_price decrements
    to find the smallest change that satisfies all three SAFE criteria:
      - EMI-to-income ratio < 30%
      - Emergency runway >= 6 months
      - Stress scenarios: 3 or more pass

    Args:
        base_params: Dict of all parameters needed for compute_all(). Expected keys match
            compute_all() signature: monthly_income, spouse_income, existing_emis,
            monthly_expenses, liquid_savings, dependents, property_price, down_payment,
            loan_tenure_years, interest_rate, carpet_area_sqft, buyer_gender,
            is_ready_to_move, maintenance_per_sqft, equivalent_rent, commute_distance_km.
        current_verdict: Current verdict string ("risky" or "reconsider"). If "safe", returns None.
        max_search_steps: Maximum iteration steps for each search dimension. Defaults to 40.

    Returns:
        Dict with keys:
            additional_down_payment_needed: float (rupees, 0 if price reduction is better)
            max_viable_property_price: float (rupees)
            months_to_save_at_current_rate: float
            monthly_savings_rate: float
        Returns None if current_verdict is "safe" or no solution found within search bounds.
    """
    if current_verdict == "safe":
        return None

    def _is_safe(computed: "ComputedNumbers") -> bool:
        stress_passed = sum(1 for s in computed.stress_scenarios if s.can_survive)
        return (
            computed.ratios.emi_to_income < 0.30
            and computed.ratios.emergency_runway_months >= 6
            and stress_passed >= 3
        )

    def _run(overrides: dict) -> "ComputedNumbers":
        params = {**base_params, **overrides}
        return compute_all(
            monthly_income=params["monthly_income"],
            spouse_income=params.get("spouse_income", 0),
            existing_emis=params.get("existing_emis", 0),
            monthly_expenses=params.get("monthly_expenses", 0),
            liquid_savings=params.get("liquid_savings", 0),
            dependents=params.get("dependents", 0),
            property_price=params["property_price"],
            down_payment=params["down_payment"],
            loan_tenure_years=params.get("loan_tenure_years", 20),
            interest_rate=params.get("interest_rate", 8.5),
            carpet_area_sqft=params.get("carpet_area_sqft", 1000),
            buyer_gender=params.get("buyer_gender", "male"),
            is_ready_to_move=params.get("is_ready_to_move", True),
            maintenance_per_sqft=params.get("maintenance_per_sqft", 5.5),
            equivalent_rent=params.get("equivalent_rent", 0.0),
            commute_distance_km=params.get("commute_distance_km", 0.0),
        )

    step = 50_000  # ₹50,000 increments
    base_dp = base_params["down_payment"]
    base_price = base_params["property_price"]

    # Search 1: Additional down payment (up to ₹50L)
    additional_dp = 0.0
    for i in range(1, max_search_steps + 1):
        extra = step * i
        if extra > 5_000_000:  # cap at ₹50L
            break
        result = _run({"down_payment": base_dp + extra})
        if _is_safe(result):
            additional_dp = extra
            break

    # Search 2: Property price reduction (down to 20% below current)
    min_price = base_price * 0.80
    price_reduction = 0.0
    for i in range(1, max_search_steps + 1):
        reduction = step * i
        new_price = base_price - reduction
        if new_price < min_price:
            break
        result = _run({"property_price": new_price})
        if _is_safe(result):
            price_reduction = reduction
            break

    if additional_dp == 0.0 and price_reduction == 0.0:
        return None

    max_viable_price = base_price - price_reduction if price_reduction > 0 else base_price

    # Estimate monthly savings rate from current income minus obligations
    monthly_income = base_params["monthly_income"]
    spouse_income = base_params.get("spouse_income", 0.0)
    existing_emis = base_params.get("existing_emis", 0.0)
    monthly_expenses = base_params.get("monthly_expenses", 0.0)
    current_emi = _run({}).emi.monthly_emi
    monthly_savings_rate = max(monthly_income + spouse_income - existing_emis - monthly_expenses - current_emi, 1.0)
    months_to_save = round(additional_dp / monthly_savings_rate, 1) if additional_dp > 0 else 0.0

    return {
        "additional_down_payment_needed": additional_dp,
        "max_viable_property_price": max_viable_price,
        "months_to_save_at_current_rate": months_to_save,
        "monthly_savings_rate": round(monthly_savings_rate, 2),
    }
