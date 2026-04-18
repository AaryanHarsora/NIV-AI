"""
Financial Reality Agent — Pure math, no AI.
Standard amortization formula. Deterministic output for the same inputs every time.
No imports from Dev 2's files.
"""
from schemas.schemas import (
    UserInput, FinancialRealityOutput, AffordabilityStatus, IndiaCostBreakdown
)
from engines.mumbai_costs import calculate_mumbai_true_cost


def calculate_true_total_cost(base_price, state, property_type, loan_amount, area_sqft=1000):
    """
    Shim that maps the old india_defaults interface to the new mumbai_costs engine.
    Called by calculate_affordability below — keeps the rest of the file unchanged.
    """
    result = calculate_mumbai_true_cost(
        base_price=base_price,
        area_sqft=area_sqft,
        floor_number=5,
        property_type=property_type,
        facing="internal",
        parking_included=False,
        parking_cost=300000,
        loan_amount=loan_amount,
        locality="mumbai",
    )
    # Return as IndiaCostBreakdown so downstream agents don't break
    return IndiaCostBreakdown(
        base_price=result.base_price,
        stamp_duty=result.stamp_duty,
        stamp_duty_rate=0.05,
        registration_fee=result.registration_fee,
        gst=result.gst,
        gst_applicable=result.is_under_construction,
        maintenance_deposit=result.maintenance_deposit,
        loan_processing_fee=result.loan_processing_fee,
        legal_charges=result.total_legal_costs,
        true_total_cost=result.true_total_acquisition_cost,
        tax_benefit_80c=150000.0,
        tax_benefit_24b=200000.0,
    )


def _calculate_emi(principal: float, annual_rate: float, tenure_years: int) -> float:
    """Standard EMI amortization formula: EMI = P * r * (1+r)^n / ((1+r)^n - 1)"""
    if principal <= 0:
        return 0.0
    if annual_rate <= 0:
        return principal / (tenure_years * 12)

    r = annual_rate / 12.0
    n = tenure_years * 12
    power = (1 + r) ** n
    emi = principal * r * power / (power - 1)
    return emi


def _reverse_loan_from_emi(target_emi: float, annual_rate: float, tenure_years: int) -> float:
    """Given a target EMI, back-calculate the maximum loan principal."""
    if target_emi <= 0:
        return 0.0
    if annual_rate <= 0:
        return target_emi * tenure_years * 12

    r = annual_rate / 12.0
    n = tenure_years * 12
    power = (1 + r) ** n
    principal = target_emi * (power - 1) / (r * power)
    return principal


def calculate_affordability(user_input: UserInput) -> FinancialRealityOutput:
    """
    Calculates the complete financial reality of a home purchase.
    Pure math. Zero LLM involvement. Deterministic.
    """
    # --- India cost breakdown ---
    loan_amount = user_input.property_price - user_input.down_payment
    if loan_amount < 0:
        loan_amount = 0.0

    india_cost_breakdown = calculate_true_total_cost(
        base_price=user_input.property_price,
        state=user_input.state,
        property_type=user_input.property_type.value,
        loan_amount=loan_amount,
        area_sqft=user_input.area_sqft if user_input.area_sqft else 1000,
    )

    # --- EMI calculation ---
    emi = _calculate_emi(loan_amount, user_input.annual_interest_rate, user_input.tenure_years)

    # --- Total interest payable ---
    tenure_months = user_input.tenure_years * 12
    if loan_amount > 0:
        total_interest_payable = (emi * tenure_months) - loan_amount
    else:
        total_interest_payable = 0.0

    # --- Financial health metrics ---
    emi_to_income_ratio = emi / user_input.monthly_income if user_input.monthly_income > 0 else float("inf")
    monthly_surplus_after_emi = user_input.monthly_income - user_input.monthly_expenses - emi

    # --- 12-month cash flow projection ---
    # Shows cumulative savings each month starting from current savings
    cash_flow_12_months = []
    running_savings = user_input.total_savings - user_input.down_payment
    savings_depletion_month = None

    for month in range(1, 13):
        running_savings += monthly_surplus_after_emi
        cash_flow_12_months.append(round(running_savings, 2))
        if running_savings <= 0 and savings_depletion_month is None:
            savings_depletion_month = month

    # --- Safe and maximum property prices ---
    # Safe: EMI = exactly 35% of income
    target_emi_safe = user_input.monthly_income * 0.35
    safe_loan = _reverse_loan_from_emi(target_emi_safe, user_input.annual_interest_rate, user_input.tenure_years)
    safe_property_price = safe_loan + user_input.down_payment

    # Maximum: EMI = exactly 50% of income
    target_emi_max = user_input.monthly_income * 0.50
    max_loan = _reverse_loan_from_emi(target_emi_max, user_input.annual_interest_rate, user_input.tenure_years)
    maximum_property_price = max_loan + user_input.down_payment

    # --- Affordability status ---
    if emi_to_income_ratio <= 0.35:
        affordability_status = AffordabilityStatus.COMFORTABLE
    elif emi_to_income_ratio <= 0.50:
        affordability_status = AffordabilityStatus.STRETCHED
    else:
        affordability_status = AffordabilityStatus.OVEREXTENDED

    return FinancialRealityOutput(
        emi=round(emi, 2),
        emi_to_income_ratio=round(emi_to_income_ratio, 4),
        monthly_surplus_after_emi=round(monthly_surplus_after_emi, 2),
        cash_flow_12_months=cash_flow_12_months,
        savings_depletion_month=savings_depletion_month,
        safe_property_price=round(safe_property_price, 2),
        maximum_property_price=round(maximum_property_price, 2),
        affordability_status=affordability_status,
        india_cost_breakdown=india_cost_breakdown,
        loan_amount=round(loan_amount, 2),
        total_interest_payable=round(total_interest_payable, 2),
    )