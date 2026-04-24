"""
Risk and affordability engine — deterministic financial health assessment.
All functions are pure, make no external calls, and return in under 10ms.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.calculations.financial import ComputedNumbers


# ---------------------------------------------------------------------------
# Risk evaluation
# ---------------------------------------------------------------------------

def evaluate_risk(computed: "ComputedNumbers") -> dict:
    ratios = computed.ratios
    stress = computed.stress_scenarios
    stress_passed = sum(1 for s in stress if s.can_survive)
    failed_scenarios = [s.name for s in stress if not s.can_survive]

    flags: list[str] = []

    if ratios.emi_to_income >= 0.50:
        flags.append("emi_ratio_critical")
    elif ratios.emi_to_income >= 0.40:
        flags.append("emi_ratio_high")
    elif ratios.emi_to_income >= 0.30:
        flags.append("emi_ratio_elevated")

    if ratios.emergency_runway_months < 3:
        flags.append("runway_critical")
    elif ratios.emergency_runway_months < 6:
        flags.append("runway_low")

    if ratios.down_payment_to_savings >= 0.80:
        flags.append("savings_depleted")
    elif ratios.down_payment_to_savings >= 0.60:
        flags.append("savings_thin")

    for name in failed_scenarios:
        flags.append(f"stress_fail_{name}")

    if "emi_ratio_critical" in flags or "runway_critical" in flags or stress_passed == 0:
        risk_level = "critical"
    elif "emi_ratio_high" in flags or "runway_low" in flags or stress_passed <= 1:
        risk_level = "high"
    elif "emi_ratio_elevated" in flags or "savings_thin" in flags or stress_passed <= 2:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "risk_level": risk_level,
        "flags": flags,
        "emi_to_income_ratio": ratios.emi_to_income,
        "emergency_runway_months": ratios.emergency_runway_months,
        "down_payment_to_savings_ratio": ratios.down_payment_to_savings,
        "stress_tests_passed": stress_passed,
        "stress_tests_total": len(stress),
        "failed_scenarios": failed_scenarios,
    }


# ---------------------------------------------------------------------------
# Financial state classification
# ---------------------------------------------------------------------------

def classify_financial_state(computed: "ComputedNumbers") -> str:
    """Returns COMFORTABLE | STRETCHED | STRESSED | CRITICAL."""
    ratios = computed.ratios
    stress_passed = sum(1 for s in computed.stress_scenarios if s.can_survive)

    if ratios.emi_to_income >= 0.50 or ratios.emergency_runway_months < 3 or stress_passed == 0:
        return "CRITICAL"
    if ratios.emi_to_income >= 0.40 or ratios.emergency_runway_months < 6 or stress_passed <= 1:
        return "STRESSED"
    if ratios.emi_to_income >= 0.30 or ratios.emergency_runway_months < 9 or stress_passed <= 2:
        return "STRETCHED"
    return "COMFORTABLE"


# ---------------------------------------------------------------------------
# Confidence score
# ---------------------------------------------------------------------------

def compute_confidence_score(computed: "ComputedNumbers") -> dict:
    """0–100 score representing how financially sound the purchase decision is."""
    ratios = computed.ratios
    stress = computed.stress_scenarios
    stress_passed = sum(1 for s in stress if s.can_survive)

    # EMI ratio component (0–40 pts)
    emi_r = ratios.emi_to_income
    if emi_r < 0.25:
        emi_score = 40
    elif emi_r < 0.30:
        emi_score = 35
    elif emi_r < 0.35:
        emi_score = 25
    elif emi_r < 0.40:
        emi_score = 15
    elif emi_r < 0.50:
        emi_score = 5
    else:
        emi_score = 0

    # Emergency runway component (0–30 pts)
    runway = ratios.emergency_runway_months
    if runway >= 12:
        runway_score = 30
    elif runway >= 9:
        runway_score = 24
    elif runway >= 6:
        runway_score = 18
    elif runway >= 3:
        runway_score = 9
    else:
        runway_score = 0

    # Stress tests component (0–30 pts)
    stress_score = round(stress_passed / max(len(stress), 1) * 30)

    total = emi_score + runway_score + stress_score

    if total >= 80:
        grade = "A"
    elif total >= 65:
        grade = "B"
    elif total >= 50:
        grade = "C"
    elif total >= 35:
        grade = "D"
    else:
        grade = "F"

    return {
        "score": total,
        "grade": grade,
        "emi_component": emi_score,
        "runway_component": runway_score,
        "stress_component": stress_score,
        "interpretation": _confidence_label(total),
    }


def _confidence_label(score: int) -> str:
    if score >= 80:
        return "Strong financial position — purchase appears well within means."
    if score >= 65:
        return "Reasonable position — manageable risk with buffers in place."
    if score >= 50:
        return "Moderate risk — proceed with caution and contingency planning."
    if score >= 35:
        return "High risk — significant financial strain expected."
    return "Very high risk — purchase not recommended in current financial state."


# ---------------------------------------------------------------------------
# Stability score
# ---------------------------------------------------------------------------

def compute_stability_score(computed: "ComputedNumbers") -> dict:
    """0–100 score for resilience to financial shocks."""
    stress = computed.stress_scenarios
    stress_passed = sum(1 for s in stress if s.can_survive)
    pct_passed = round(stress_passed / max(len(stress), 1) * 100)

    runway = computed.ratios.emergency_runway_months
    dp_ratio = computed.ratios.down_payment_to_savings

    if runway >= 12:
        runway_bonus = 20
    elif runway >= 9:
        runway_bonus = 15
    elif runway >= 6:
        runway_bonus = 10
    elif runway >= 3:
        runway_bonus = 5
    else:
        runway_bonus = 0

    if dp_ratio < 0.40:
        savings_bonus = 20
    elif dp_ratio < 0.60:
        savings_bonus = 10
    elif dp_ratio < 0.80:
        savings_bonus = 5
    else:
        savings_bonus = 0

    score = min(round(pct_passed * 0.60 + runway_bonus + savings_bonus), 100)

    return {
        "score": score,
        "stress_tests_passed": stress_passed,
        "stress_tests_total": len(stress),
        "pct_stress_survived": pct_passed,
        "runway_months": runway,
        "savings_depletion_ratio": dp_ratio,
        "interpretation": _stability_label(score),
    }


def _stability_label(score: int) -> str:
    if score >= 75:
        return "Highly stable — resilient to most financial shocks."
    if score >= 55:
        return "Moderately stable — can handle typical disruptions."
    if score >= 35:
        return "Fragile — vulnerable to income disruption or unexpected expenses."
    return "Unstable — likely to face distress under any major shock."


# ---------------------------------------------------------------------------
# Affordability envelope
# ---------------------------------------------------------------------------

def compute_affordability_envelope(
    monthly_income: float,
    spouse_income: float,
    existing_emis: float,
    monthly_expenses: float,
    liquid_savings: float,
    interest_rate: float,
    loan_tenure_years: int,
) -> dict:
    """
    Returns safe / stretch / hard-max property price bounds from financial profile alone.
    No property params needed — powers pre-search guidance.
    """
    household_income = monthly_income + spouse_income
    r = interest_rate / 12 / 100
    n = loan_tenure_years * 12

    # Present-value annuity factor: converts max monthly EMI → max loan amount
    if r > 0 and n > 0:
        pv_factor = ((1 + r) ** n - 1) / (r * (1 + r) ** n)
    else:
        pv_factor = float(n)

    def _max_loan(max_emi: float) -> float:
        return round(max(max_emi, 0) * pv_factor, 2)

    def _loan_to_property(loan: float) -> float:
        # Try 20 % → 25 % → 30 % down payment from savings; fall back to savings as DP.
        for dp_pct in (0.20, 0.25, 0.30):
            dp = round(loan / (1 - dp_pct) * dp_pct, 2)
            if dp <= liquid_savings:
                return round(loan + dp, 2)
        return round(loan + liquid_savings, 2)

    safe_emi   = max(round(household_income * 0.30 - existing_emis, 2), 0.0)
    stretch_emi = max(round(household_income * 0.40 - existing_emis, 2), 0.0)
    hard_emi   = max(round(household_income * 0.50 - existing_emis, 2), 0.0)

    safe_loan    = _max_loan(safe_emi)
    stretch_loan = _max_loan(stretch_emi)
    hard_loan    = _max_loan(hard_emi)

    # Savings-constrained ceiling: if you can only afford 20 % DP from savings
    savings_ceiling = round(liquid_savings / 0.20, 2) if liquid_savings > 0 else 0.0

    return {
        "household_income": household_income,
        "safe_max_property": _loan_to_property(safe_loan),
        "safe_max_emi": safe_emi,
        "safe_max_loan": safe_loan,
        "stretch_max_property": _loan_to_property(stretch_loan),
        "stretch_max_emi": stretch_emi,
        "stretch_max_loan": stretch_loan,
        "hard_max_property": _loan_to_property(hard_loan),
        "hard_max_emi": hard_emi,
        "hard_max_loan": hard_loan,
        "savings_constrained_max_property": savings_ceiling,
        "note": "Safe: EMI ≤ 30% income. Stretch: EMI ≤ 40%. Hard max: EMI ≤ 50%. Down payment drawn from liquid savings.",
    }


# ---------------------------------------------------------------------------
# Survival timeline
# ---------------------------------------------------------------------------

def compute_survival_timeline(computed: "ComputedNumbers") -> dict:
    """Maps each stress scenario to its survival metrics."""
    scenarios: dict = {}
    for s in computed.stress_scenarios:
        scenarios[s.name] = {
            "can_survive": s.can_survive,
            "months_before_default": s.months_before_default,
            "key_number": s.key_number,
            "description": s.description,
        }

    finite_months = [
        s.months_before_default
        for s in computed.stress_scenarios
        if s.months_before_default is not None
    ]
    worst_case = round(min(finite_months), 1) if finite_months else None

    return {
        "scenarios": scenarios,
        "worst_case_months_before_default": worst_case,
        "emergency_runway_months": computed.ratios.emergency_runway_months,
        "post_purchase_savings": computed.post_purchase_savings,
    }


# ---------------------------------------------------------------------------
# Action plan
# ---------------------------------------------------------------------------

def get_action_plan(computed: "ComputedNumbers") -> list:
    """Returns a prioritised list of concrete recommendations."""
    actions: list[dict] = []
    ratios = computed.ratios
    stress = computed.stress_scenarios
    stress_passed = sum(1 for s in stress if s.can_survive)

    # EMI ratio actions
    if ratios.emi_to_income >= 0.50:
        actions.append({
            "priority": "critical",
            "action": "reduce_property_price",
            "message": (
                f"EMI consumes {ratios.emi_to_income:.0%} of income — "
                "consider a cheaper property or substantially higher down payment."
            ),
        })
    elif ratios.emi_to_income >= 0.40:
        actions.append({
            "priority": "high",
            "action": "increase_down_payment",
            "message": (
                f"EMI at {ratios.emi_to_income:.0%} of income leaves little margin — "
                "increase down payment to bring EMI below 35%."
            ),
        })
    elif ratios.emi_to_income >= 0.30:
        actions.append({
            "priority": "medium",
            "action": "limit_new_obligations",
            "message": (
                f"EMI at {ratios.emi_to_income:.0%} of income is manageable but stretched — "
                "avoid taking on any new debt."
            ),
        })

    # Emergency runway actions
    if ratios.emergency_runway_months < 6:
        actions.append({
            "priority": "critical",
            "action": "build_emergency_fund",
            "message": (
                f"Only {ratios.emergency_runway_months:.1f} months of savings post-purchase — "
                "build at least 6 months before closing."
            ),
        })
    elif ratios.emergency_runway_months < 9:
        actions.append({
            "priority": "medium",
            "action": "build_emergency_fund",
            "message": (
                f"{ratios.emergency_runway_months:.1f} months runway is thin — "
                "aim for 9+ months before purchase."
            ),
        })

    # Savings depletion action
    if ratios.down_payment_to_savings >= 0.80:
        actions.append({
            "priority": "high",
            "action": "preserve_savings",
            "message": (
                "Down payment depletes over 80% of liquid savings — "
                "you will have very little liquidity post-purchase."
            ),
        })

    # Stress test action
    if stress_passed < 2:
        actions.append({
            "priority": "high",
            "action": "stress_test_preparation",
            "message": (
                f"Only {stress_passed} of {len(stress)} stress scenarios survived — "
                "financial vulnerability is high."
            ),
        })

    # Job-loss specific
    job_loss = next((s for s in stress if s.name == "job_loss_6_months"), None)
    if job_loss and not job_loss.can_survive:
        months = job_loss.months_before_default or 0
        actions.append({
            "priority": "high",
            "action": "job_loss_buffer",
            "message": (
                f"Savings last only {months:.0f} months if primary earner loses income — "
                "build a 6-month income buffer before buying."
            ),
        })

    if not actions:
        actions.append({
            "priority": "low",
            "action": "maintain_discipline",
            "message": (
                "Financial position is strong — maintain savings discipline "
                "and avoid taking on new liabilities after purchase."
            ),
        })

    return actions
