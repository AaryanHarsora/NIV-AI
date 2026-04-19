"""Agent 3: Risk Simulator — contextualizes pre-computed stress scenarios."""
from __future__ import annotations
import logging
from backend.llm.client import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Risk Simulator agent in a home-buying decision system for Indian buyers.
You receive pre-computed stress test results. Numbers are CORRECT. Add mitigation advice and severity ratings.

overall_resilience: "strong" (3-4 pass), "moderate" (2 pass), "weak" (1 pass), "fragile" (0 pass)
severity per scenario: "low", "medium", "high", "critical"

MITIGATION RULES — match advice to the outcome:
- If can_survive=TRUE: Give forward-looking advice to MAINTAIN that position. Do NOT say "save more before buying" — they already pass.
  Examples: "Maintain this buffer", "Consider a rate lock to protect against hikes", "Keep 3 months expenses liquid"
- If can_survive=FALSE: Give specific action to fix the gap. "Save Rs.X more", "Reduce loan by Rs.Y", be concrete.

Respond ONLY with JSON:
{
  "scenarios": [{"name": "<n>", "description": "<d>", "can_survive": <bool>, "months_before_default": <n|null>, "key_number": "<s>", "mitigation": "<specific advice matching pass/fail>", "severity": "<level>"}],
  "overall_resilience": "<strong|moderate|weak|fragile>",
  "critical_vulnerability": "<single biggest risk>",
  "reasoning": "<2-3 paragraphs>"
}"""


async def run(llm: LLMClient, context: dict, financial_analysis: dict, computed_numbers: dict,
              stress_results: list, raw_input: dict) -> dict:
    fin = raw_input["financial"]
    scenario_text = ""
    for s in stress_results:
        scenario_text += f"\n{s['name']}: survive={s['can_survive']}, months={s.get('months_before_default','N/A')}, key={s['key_number']}, new_emi={s.get('new_emi','N/A')}, new_ratio={s.get('new_ratio','N/A')}"
    msg = f"""Contextualize these stress test results:
Buyer: {fin["employment_type"]}, {fin["years_in_current_job"]}yrs, Income Rs.{fin["monthly_income"]:,.0f}, Dependents {fin["dependents"]}, Post-purchase savings Rs.{computed_numbers["post_purchase_savings"]:,.0f}
Affordability verdict: {financial_analysis.get("affordability_verdict")}
Scenarios (numbers are exact):{scenario_text}
Red flags: {financial_analysis.get("red_flags", [])}"""
    raw = await llm.run_agent(SYSTEM_PROMPT, msg)
    result = llm.parse_json(raw)
    logger.info("Risk simulator complete — resilience: %s", result.get("overall_resilience"))
    return result