import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.base_agent import BaseAgent
from schemas.schemas import ValidationOutput, AssumptionItem, ConflictItem


SYSTEM_PROMPT = """
You are a meticulous financial audit agent.
Your job is to read all agent outputs and find two things.
First, log every assumption made anywhere in the analysis — things like income assumed stable, property prices will appreciate, no major expenses expected.
Second, find contradictions — places where one agent's conclusion conflicts with another or where an assumption contradicts the simulation data.
You are not here to provide advice. You are here to find gaps, inconsistencies, and risky assumptions.
You always respond in valid JSON matching the exact format requested.
"""


class ValidationAgent(BaseAgent):

    def __init__(self):
        super().__init__(
            name="ValidationAgent",
            persona="Financial audit agent that logs assumptions and detects conflicts",
            system_prompt=SYSTEM_PROMPT
        )

    async def validate(self, blackboard: dict) -> ValidationOutput:
        context = self._build_context(blackboard)
        prompt = self._build_validation_prompt(context)
        raw = await self.call(prompt)
        return self._parse_output(raw)

    def _build_context(self, blackboard: dict) -> dict:
        return self.extract_blackboard_context(blackboard, [
            "user_input",
            "financial_reality",
            "all_scenarios",
            "risk_score",
            "behavioral_analysis",
            "india_cost_breakdown"
        ])

    def _build_validation_prompt(self, context: dict) -> str:
        return self.build_prompt(
            context=context,
            task="""
Read all the analysis data carefully.

For assumptions_log, identify every assumption made in the analysis.
For each assumption provide:
- assumption: what is being assumed
- source_agent: which agent or data source made this assumption
- flagged: true if this assumption is risky or unverified
- flag_reason: why it is risky if flagged is true, null otherwise

For conflicts, identify every contradiction between agent outputs or between assumptions and data.
For each conflict provide:
- description: what the contradiction is
- agents_involved: which agents or data sources are in conflict
- severity: low, medium, or high
- resolution_suggestion: how this conflict could be resolved

data_quality_score is your assessment of how reliable the inputs are from 0 to 100.
Deduct points for missing data, unrealistic values, or inconsistencies.

Respond in this exact JSON format:
{
    "assumptions_log": [
        {
            "assumption": "income will remain stable over loan tenure",
            "source_agent": "financial_reality",
            "flagged": true,
            "flag_reason": "no evidence of income stability provided"
        }
    ],
    "flagged_assumptions": [
        {
            "assumption": "income will remain stable over loan tenure",
            "source_agent": "financial_reality",
            "flagged": true,
            "flag_reason": "no evidence of income stability provided"
        }
    ],
    "conflicts": [
        {
            "description": "description of conflict",
            "agents_involved": ["agent1", "agent2"],
            "severity": "medium",
            "resolution_suggestion": "how to resolve"
        }
    ],
    "data_quality_score": 78
}
"""
        )

    def _parse_output(self, raw: dict) -> ValidationOutput:
        assumptions_log = [
            AssumptionItem(
                assumption=a["assumption"],
                source_agent=a["source_agent"],
                flagged=a["flagged"],
                flag_reason=a.get("flag_reason")
            )
            for a in raw.get("assumptions_log", [])
        ]
        flagged_assumptions = [
            AssumptionItem(
                assumption=a["assumption"],
                source_agent=a["source_agent"],
                flagged=a["flagged"],
                flag_reason=a.get("flag_reason")
            )
            for a in raw.get("flagged_assumptions", [])
        ]
        conflicts = [
            ConflictItem(
                description=c["description"],
                agents_involved=c["agents_involved"],
                severity=c["severity"],
                resolution_suggestion=c["resolution_suggestion"]
            )
            for c in raw.get("conflicts", [])
        ]
        return ValidationOutput(
            assumptions_log=assumptions_log,
            flagged_assumptions=flagged_assumptions,
            conflicts=conflicts,
            data_quality_score=raw.get("data_quality_score", 50.0)
        )