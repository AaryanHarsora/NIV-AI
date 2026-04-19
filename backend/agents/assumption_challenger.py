"""Agent 5: Assumption Challenger — adversarial agent that finds holes in the decision."""
from __future__ import annotations
import logging
from backend.llm.client import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Assumption Challenger — a financial devil's advocate for Indian home purchases.
Find EVERY way this decision could go wrong. Be specific with rupee amounts.

CRITICAL RULE: Only challenge things that are ACTUALLY UNKNOWN or NOT PROVIDED.
If the user provided spouse_income, do NOT challenge it as "unknown".
If the user provided existing_emis, do NOT challenge them as "possibly higher".
If the user provided monthly_expenses, do NOT fabricate alternative expense levels.
Only raise challenges about things genuinely not captured in the input — future unknowns, external risks, market risks.

BAD example (user provided spouse income of Rs.1,00,000):
"Spouse's income is not confirmed" — WRONG, it was provided

GOOD example:
"You assumed 9% salary growth. IT sector median has been 6-8% since 2022. At 7%, EMI/income rises to 24% in year 5."

severity: "critical" (alone causes distress), "high" (materially changes decision), "medium" (plan for it), "low" (minor)
Generate 3-5 challenges focused on FUTURE risks, market risks, and external factors — NOT things the user already told us.

Respond ONLY with JSON:
{
  "challenges": [{"assumption": "<what is being assumed>", "challenge": "<why this could be wrong, with data>", "impact": "<rupee impact>", "severity": "<level>"}],
  "blind_spots": ["<unconsidered factor>"],
  "emotional_flags": ["<bias detected>"],
  "reasoning": "<2-3 paragraphs>"
}"""


async def run(llm: LLMClient, context: dict, financial_analysis: dict, risk_analysis: dict,
              property_analysis: dict, computed_numbers: dict, raw_input: dict) -> dict:
    fin = raw_input["financial"]
    prop = raw_input["property"]
    survived = sum(1 for s in risk_analysis.get("scenarios", []) if s.get("can_survive", False))

    # Pass ALL provided data explicitly so agent doesn't challenge things we already know
    msg = f"""Challenge the FUTURE RISKS and UNKNOWNS in this decision. Do NOT re-challenge data already provided below.

WHAT THE BUYER HAS ALREADY TOLD US (do not challenge these):
- Primary income: Rs.{fin["monthly_income"]:,.0f}/mo
- Spouse income: Rs.{fin["spouse_income"]:,.0f}/mo (household total: Rs.{fin["monthly_income"]+fin["spouse_income"]:,.0f})
- Employment: {fin["employment_type"]}, {fin["years_in_current_job"]} years
- Existing EMIs: Rs.{fin["existing_emis"]:,.0f}/mo
- Monthly expenses: Rs.{fin["monthly_expenses"]:,.0f}/mo
- Liquid savings: Rs.{fin["liquid_savings"]:,.0f}
- Dependents: {fin["dependents"]}
- Growth assumption: {fin["expected_annual_growth_pct"]}%
- Property price: Rs.{prop["property_price"]:,.0f}, Location: {prop["location_area"]}
- Ready to move: {prop["is_ready_to_move"]}, RERA: {prop.get("is_rera_registered")}
- Notes: {fin["financial_notes"] or "None"} | {prop["property_notes"] or "None"}

COMPUTED FACTS (correct — do not recalculate):
EMI/income: {computed_numbers["emi_to_income_ratio"]:.1%}, Runway: {computed_numbers["emergency_runway_months"]:.1f} months
Stress tests passed: {survived}/4, Break-even: {computed_numbers["rent_vs_buy_break_even_years"]:.1f} years
Financial verdict: {financial_analysis.get("affordability_verdict")}, Price verdict: {property_analysis.get("price_assessment", {}).get("verdict")}
Critical vulnerability: {risk_analysis.get("critical_vulnerability")}

NOW challenge only: future income risks, market risks, external economic factors, things genuinely not captured above."""

    raw = await llm.run_agent(SYSTEM_PROMPT, msg, max_tokens=3500)
    result = llm.parse_json(raw)
    logger.info("Assumption challenger complete — %d challenges", len(result.get("challenges", [])))
    return result