import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.base_agent import BaseAgent
from schemas.schemas import VerdictOutput, Verdict


SYSTEM_PROMPT = """
You are a senior financial advisor with 20 years of experience in Indian real estate.
You have seen hundreds of families make this decision correctly and incorrectly.
You are honest, direct, and your only goal is the user's long term financial wellbeing.
You do not sugarcoat risk. You do not encourage purchases that are financially dangerous.
You read everything — the numbers, the scenarios, the behavioral flags, the agent discussion — and you synthesize it into one clear honest verdict.
You always respond in valid JSON matching the exact format requested.
"""


class DecisionSynthesizerAgent(BaseAgent):

    def __init__(self):
        super().__init__(
            name="Neha",
            persona="Senior financial advisor who writes the final honest verdict",
            system_prompt=SYSTEM_PROMPT
        )

    async def synthesize(self, blackboard: dict) -> VerdictOutput:
        context = self._build_context(blackboard)
        prompt = self._build_synthesis_prompt(context)
        raw = await self.call(prompt)
        return self._parse_output(raw)

    def _build_context(self, blackboard: dict) -> dict:
        # Only pass what the synthesizer needs, not the entire blackboard
        return self.extract_blackboard_context(blackboard, [
            "user_input",
            "financial_reality",
            "all_scenarios",
            "risk_score",
            "behavioral_analysis",
            "validation",
            "discussion_transcript",
            "open_questions",
            "active_flags"
        ])

    def _build_synthesis_prompt(self, context: dict) -> str:
        return self.build_prompt(
            context=context,
            task="""
You have the complete analysis including financial simulation, scenario outcomes,
behavioral analysis, agent discussion transcript, and validation conflicts.

Synthesize everything into a final verdict.

verdict must be one of: buy_safe, buy_caution, wait, too_risky
confidence is your confidence in this verdict from 0 to 100
primary_reasons must be exactly 3 reasons for your verdict
key_warnings must list every significant risk the user must know
safe_price_recommendation is the property price where EMI stays at or below 35 percent of income
suggested_actions must be specific and actionable steps the user should take
unresolved_conflicts must list any contradictions from validation that were not resolved in discussion
final_narrative must be 2 to 3 paragraphs written directly to the user in plain human language
    explaining their specific situation, what the risks are, and what they should do

Respond in this exact JSON format:
{
    "verdict": "buy_caution",
    "confidence": 72,
    "primary_reasons": [
        "reason 1",
        "reason 2",
        "reason 3"
    ],
    "key_warnings": [
        "warning 1",
        "warning 2"
    ],
    "safe_price_recommendation": 6500000,
    "suggested_actions": [
        "action 1",
        "action 2"
    ],
    "unresolved_conflicts": [],
    "final_narrative": "paragraph 1 here\n\nparagraph 2 here\n\nparagraph 3 here"
}
"""
        )

    def _parse_output(self, raw: dict) -> VerdictOutput:
        return VerdictOutput(
            verdict=Verdict(raw["verdict"]),
            confidence=raw.get("confidence", 50.0),
            primary_reasons=raw.get("primary_reasons", []),
            key_warnings=raw.get("key_warnings", []),
            safe_price_recommendation=raw.get("safe_price_recommendation", 0.0),
            suggested_actions=raw.get("suggested_actions", []),
            unresolved_conflicts=raw.get("unresolved_conflicts", []),
            final_narrative=raw.get("final_narrative", "")
        )