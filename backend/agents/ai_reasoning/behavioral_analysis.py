import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.base_agent import BaseAgent
from schemas.schemas import BehavioralAnalysisOutput, BiasFlagItem, BiasType, BiasSeverity


SYSTEM_PROMPT = """
You are a behavioral psychologist specializing in financial decision-making for Indian households.
You analyze how people describe their home buying situation and identify cognitive and emotional biases.
You are calm, observational, and non-judgmental.
You look for evidence in both what people say and what their numbers imply.
You never make assumptions without evidence from the inputs.
You always respond in valid JSON matching the exact format requested.
"""


class BehavioralAnalysisAgent(BaseAgent):

    def __init__(self):
        super().__init__(
            name="BehavioralAnalysis",
            persona="Behavioral psychologist who identifies financial decision biases",
            system_prompt=SYSTEM_PROMPT
        )

    async def analyze(
        self,
        behavioral_answers: list,
        financial_inputs: dict,
        india_cost_breakdown: dict
    ) -> BehavioralAnalysisOutput:

        context = self._build_context(
            behavioral_answers, financial_inputs, india_cost_breakdown
        )
        prompt = self._build_analysis_prompt(context)
        raw = await self.call(prompt)
        return self._parse_output(raw)

    def _build_context(
        self,
        behavioral_answers: list,
        financial_inputs: dict,
        india_cost_breakdown: dict
    ) -> dict:
        return {
            "behavioral_answers": behavioral_answers,
            "financial_inputs": {
                "monthly_income": financial_inputs.get("monthly_income"),
                "monthly_expenses": financial_inputs.get("monthly_expenses"),
                "total_savings": financial_inputs.get("total_savings"),
                "down_payment": financial_inputs.get("down_payment"),
                "property_price": financial_inputs.get("property_price"),
                "tenure_years": financial_inputs.get("tenure_years"),
                "annual_interest_rate": financial_inputs.get("annual_interest_rate"),
                "age": financial_inputs.get("age"),
                "state": financial_inputs.get("state"),
            },
            "true_total_cost": india_cost_breakdown.get("true_total_cost"),
            "cost_vs_savings_ratio": (
                india_cost_breakdown.get("true_total_cost", 0)
                / max(financial_inputs.get("total_savings", 1), 1)
            )
        }

    def _build_analysis_prompt(self, context: dict) -> str:
        return self.build_prompt(
            context=context,
            task="""
Analyze the behavioral questionnaire answers and financial inputs.
Identify all cognitive and emotional biases present.

For each bias found you must provide:
- bias_type: one of FOMO, overconfidence, anchoring, social_pressure, scarcity_bias, optimism_bias, denial
- severity: one of low, medium, high
- evidence: exact quote or specific data point from inputs that triggered this flag
- implication: what financial risk does this bias create for this user

Also provide:
- behavioral_risk_score: overall score from 0 to 10 where 10 is highest risk
- recommended_questions: list of 2 to 3 follow up questions to ask the user to surface deeper bias
- summary: 2 to 3 sentence plain English behavioral profile of this user
- emotionally_committed: true if user shows signs of already committing to a specific property

Respond in this exact JSON format:
{
    "bias_flags": [
        {
            "bias_type": "FOMO",
            "severity": "high",
            "evidence": "exact evidence here",
            "implication": "financial risk implication here"
        }
    ],
    "behavioral_risk_score": 7.5,
    "recommended_questions": [
        "question 1",
        "question 2"
    ],
    "summary": "plain English summary here",
    "emotionally_committed": false
}
"""
        )

    def _parse_output(self, raw: dict) -> BehavioralAnalysisOutput:
        bias_flags = [
            BiasFlagItem(
                bias_type=BiasType(flag["bias_type"]),
                severity=BiasSeverity(flag["severity"]),
                evidence=flag["evidence"],
                implication=flag["implication"]
            )
            for flag in raw.get("bias_flags", [])
        ]
        return BehavioralAnalysisOutput(
            bias_flags=bias_flags,
            behavioral_risk_score=raw.get("behavioral_risk_score", 0.0),
            recommended_questions=raw.get("recommended_questions", []),
            summary=raw.get("summary", ""),
            emotionally_committed=raw.get("emotionally_committed", False)
        )