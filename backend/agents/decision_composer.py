"""Agent 6: Decision Composer — final verdict synthesis. Uses Gemini with Groq fallback."""
from __future__ import annotations
import logging
from backend.llm.client import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Decision Composer — the final judge in a home-buying decision system for Indian buyers.
Synthesize all 5 agent outputs into ONE clear verdict.

VERDICT RULES — follow these strictly in order:
- "safe": comfortable affordability (EMI/income <30%) AND passes 3+ stress tests AND price is fair/good_value AND runway >6 months
- "reconsider": unaffordable (EMI/income >45%) OR runway <3 months OR fails 3+ stress tests OR critical property construction/legal flags
- "risky": everything else — stretched affordability (30-45%) OR fails 2 stress tests OR slightly overpriced OR thin runway (3-6 months)

CRITICAL RULE: Assumption challenges from Agent 5 are adversarial hypotheticals — they should INFORM your reasoning but NEVER alone change a verdict. A buyer with 19% EMI/income, 18 months runway, and 4/4 stress tests is SAFE even if Agent 5 raised concerns. Weight the hard numbers over hypothetical challenges.

TONE: Trusted advisor. Plain language. Concrete rupee amounts. Always offer a path forward.

Respond ONLY with JSON:
{
  "verdict": "<safe|risky|reconsider>",
  "confidence_score": <1-10>,
  "verdict_reason": "<one sentence>",
  "top_reasons": ["<most important reason>", "<2>", "<3>", "<4>", "<5>"],
  "conditions_for_safety": ["<what would make this safe>"],
  "recommended_actions": ["<concrete action>"],
  "full_reasoning": "<3-5 paragraphs tying everything together>"
}"""


async def run(
    llm: LLMClient,
    context: dict,
    financial_analysis: dict,
    risk_analysis: dict,
    property_analysis: dict,
    assumption_analysis: dict,
    computed_numbers: dict,
    raw_input: dict,
) -> dict:
    user_message = _build_message(
        context, financial_analysis, risk_analysis,
        property_analysis, assumption_analysis, computed_numbers, raw_input,
    )
    raw_response = await llm.run_final_agent(SYSTEM_PROMPT, user_message)
    result = llm.parse_json(raw_response)
    logger.info("Decision composer complete — verdict: %s", result.get("verdict"))
    return result


def _build_message(
    context: dict,
    financial: dict,
    risk: dict,
    property_analysis: dict,
    assumptions: dict,
    computed: dict,
    raw_input: dict,
) -> str:
    fin = raw_input["financial"]
    prop = raw_input["property"]

    scenarios = risk.get("scenarios", [])
    survived = sum(1 for s in scenarios if s.get("can_survive", False))
    total_scenarios = len(scenarios)

    challenges = assumptions.get("challenges", [])
    critical = sum(1 for c in challenges if c.get("severity") in ("critical", "high"))

    user_profile = context.get("user_profile") or {}
    stability = user_profile.get("employment_stability", "unknown")
    risk_capacity = user_profile.get("risk_capacity", "unknown")
    implicit_assumptions = context.get("implicit_assumptions", [])
    missing_data = context.get("missing_data", [])

    red_flags = financial.get("red_flags", [])
    overall_resilience = risk.get("overall_resilience", "unknown")
    critical_vulnerability = risk.get("critical_vulnerability", "unknown")

    price_assessment = property_analysis.get("price_assessment") or {}
    price_verdict = price_assessment.get("verdict", "unknown")
    property_flags = [f["flag"] for f in property_analysis.get("property_flags", [])]

    blind_spots = assumptions.get("blind_spots", [])
    emotional_flags = assumptions.get("emotional_flags", [])

    household_income = fin['monthly_income'] + fin.get('spouse_income', 0)
    monthly_surplus = household_income - computed['monthly_ownership_cost'] - fin.get('existing_emis', 0) - fin.get('monthly_expenses', 0)

    lines = [
        "Produce the final verdict by synthesizing all agent analyses.",
        "",
        "BUYER SUMMARY:",
        f"Income: Rs.{fin['monthly_income']:,.0f}/mo + spouse Rs.{fin.get('spouse_income',0):,.0f} = HOUSEHOLD Rs.{household_income:,.0f}/mo ({fin['employment_type']})",
        f"Property Rs.{prop['property_price']:,.0f} in {prop['location_area']}",
        f"Loan: Rs.{computed['loan_amount']:,.0f} at {prop['expected_interest_rate']}% for {prop['loan_tenure_years']}yrs",
        f"Monthly surplus after ALL obligations: Rs.{monthly_surplus:,.0f}",
        "",
        "AGENT 1 — Context:",
        f"Employment stability: {stability}",
        f"Risk capacity: {risk_capacity}",
        f"Implicit assumptions: {implicit_assumptions}",
        f"Missing data: {missing_data}",
        "",
        "AGENT 2 — Financial:",
        f"Verdict: {financial.get('affordability_verdict', 'unknown')}",
        f"EMI/income: {computed['emi_to_income_ratio']:.1%}",
        f"Total housing/income: {computed['total_housing_to_income_ratio']:.1%}",
        f"Emergency runway: {computed['emergency_runway_months']:.1f} months",
        f"Post-purchase savings: Rs.{computed['post_purchase_savings']:,.0f}",
        f"Red flags: {red_flags}",
        "",
        "AGENT 3 — Risk:",
        f"Stress tests passed: {survived}/{total_scenarios}",
        f"Overall resilience: {overall_resilience}",
        f"Critical vulnerability: {critical_vulnerability}",
        "",
        "AGENT 4 — Property:",
        f"Price verdict: {price_verdict}",
        f"Property flags: {property_flags}",
        f"Rent vs buy break-even: {computed['rent_vs_buy_break_even_years']:.1f} years",
        "",
        "AGENT 5 — Assumptions:",
        f"Total challenges: {len(challenges)}, critical/high: {critical}",
        f"Blind spots: {blind_spots}",
        f"Emotional flags: {emotional_flags}",
        "",
        "Now produce the final verdict with full reasoning.",
    ]

    return "\n".join(lines)