import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.base_agent import BaseAgent
from schemas.schemas import (
    PresentationOutput, CashFlowChartData, ChartDataset,
    ScenarioComparisonData, AffordabilityBarData, RiskGaugeData,
    WarningCard, PDFContent, PDFSection, RiskLabel
)


SYSTEM_PROMPT = """
You are a financial communication specialist.
You take complex financial analysis outputs and translate them into clear, plain English.
You never generate new analysis or change any numbers.
You only translate, explain, and format what you are given.
You write for a financially literate Indian professional aged 28 to 42.
You are direct, clear, and never use jargon without explaining it.
You always respond in valid JSON matching the exact format requested.
"""


class PresentationAgent(BaseAgent):

    def __init__(self):
        super().__init__(
            name="PresentationAgent",
            persona="Financial communication specialist who translates analysis to plain English",
            system_prompt=SYSTEM_PROMPT
        )

    async def present(self, blackboard: dict) -> PresentationOutput:
        context = self._build_context(blackboard)
        prompt = self._build_presentation_prompt(context)
        raw = await self.call(prompt)
        return self._parse_output(raw, blackboard)

    def _build_context(self, blackboard: dict) -> dict:
        return self.extract_blackboard_context(blackboard, [
            "user_input",
            "financial_reality",
            "all_scenarios",
            "risk_score",
            "behavioral_analysis",
            "validation",
            "verdict"
        ])

    def _build_presentation_prompt(self, context: dict) -> str:
        return self.build_prompt(
            context=context,
            task="""
Translate all the analysis into plain English for the user.

formatted_risk_summary: 2 to 3 sentences explaining the risk score in plain English
scenario_explanations: one plain English sentence per scenario explaining what happens
    keys must be: base_case, income_drop_30pct, job_loss_6_months, interest_rate_hike_2pct, emergency_expense_5L
behavioral_summary: 2 sentences explaining the behavioral flags without jargon
warning_cards: list of the most important warnings the user must see
    each card has title, description, severity (low/medium/high), category (financial/behavioral/assumption)
verdict_display: structured display object with verdict label, confidence display text, and recommendation text

Respond in this exact JSON format:
{
    "formatted_risk_summary": "plain English risk summary here",
    "scenario_explanations": {
        "base_case": "explanation here",
        "income_drop_30pct": "explanation here",
        "job_loss_6_months": "explanation here",
        "interest_rate_hike_2pct": "explanation here",
        "emergency_expense_5L": "explanation here"
    },
    "behavioral_summary": "plain English behavioral summary here",
    "warning_cards": [
        {
            "title": "warning title",
            "description": "warning description",
            "severity": "high",
            "category": "financial"
        }
    ],
    "verdict_display": {
        "label": "High Risk",
        "confidence_text": "We are 78% confident in this assessment",
        "recommendation_text": "short recommendation here"
    }
}
"""
        )

    def _parse_output(self, raw: dict, blackboard: dict) -> PresentationOutput:
        # Build chart data from blackboard directly, not from LLM
        cash_flow_chart_data = self._build_cash_flow_chart(blackboard)
        scenario_comparison_data = self._build_scenario_comparison(blackboard)
        affordability_bar_data = self._build_affordability_bar(blackboard)
        risk_gauge_data = self._build_risk_gauge(blackboard)
        pdf_content = self._build_pdf_content(blackboard, raw)

        warning_cards = [
            WarningCard(
                title=w["title"],
                description=w["description"],
                severity=w["severity"],
                category=w["category"]
            )
            for w in raw.get("warning_cards", [])
        ]

        return PresentationOutput(
            formatted_risk_summary=raw.get("formatted_risk_summary", ""),
            scenario_explanations=raw.get("scenario_explanations", {}),
            behavioral_summary=raw.get("behavioral_summary", ""),
            cash_flow_chart_data=cash_flow_chart_data,
            scenario_comparison_data=scenario_comparison_data,
            affordability_bar_data=affordability_bar_data,
            risk_gauge_data=risk_gauge_data,
            warning_cards=warning_cards,
            verdict_display=raw.get("verdict_display", {}),
            pdf_content=pdf_content
        )

    def _build_cash_flow_chart(self, blackboard: dict) -> CashFlowChartData:
        financial_reality = blackboard.get("financial_reality", {})
        all_scenarios = blackboard.get("all_scenarios", {})
        labels = [f"Month {i+1}" for i in range(12)]

        datasets = []

        # Base case cash flow from financial reality
        base_flow = financial_reality.get("cash_flow_12_months", [0] * 12)
        if hasattr(base_flow, '__iter__'):
            datasets.append(ChartDataset(
                label="Base Case",
                data=list(base_flow),
                color="#22c55e"
            ))

        scenario_colors = {
            "income_drop_30pct": "#f97316",
            "job_loss_6_months": "#ef4444",
            "interest_rate_hike_2pct": "#eab308",
            "emergency_expense_5L": "#a855f7"
        }

        scenario_labels = {
            "income_drop_30pct": "Income Drop 30%",
            "job_loss_6_months": "Job Loss 6 Months",
            "interest_rate_hike_2pct": "Rate Hike +2%",
            "emergency_expense_5L": "Emergency ₹5L"
        }

        for key, color in scenario_colors.items():
            scenario = all_scenarios.get(key, {})
            if scenario:
                buffer = scenario.get("buffer_months", 0)
                survivable = scenario.get("survivable", True)
                monthly_shortfall = scenario.get("monthly_shortfall", 0) or 0
                base = list(base_flow)
                scenario_flow = []
                for i in range(12):
                    if not survivable and i >= buffer:
                        scenario_flow.append(base[i] - monthly_shortfall if i < len(base) else -monthly_shortfall)
                    else:
                        scenario_flow.append(base[i] if i < len(base) else 0)
                datasets.append(ChartDataset(
                    label=scenario_labels[key],
                    data=scenario_flow,
                    color=color
                ))

        return CashFlowChartData(labels=labels, datasets=datasets)

    def _build_scenario_comparison(self, blackboard: dict) -> ScenarioComparisonData:
        all_scenarios = blackboard.get("all_scenarios", {})
        severity_color_map = {
            "low": "#22c55e",
            "medium": "#eab308",
            "high": "#f97316",
            "critical": "#ef4444"
        }
        names = []
        buffers = []
        survivable = []
        colors = []
        scenario_keys = [
            ("base_case", "Base Case"),
            ("income_drop_30pct", "Income -30%"),
            ("job_loss_6_months", "Job Loss 6mo"),
            ("interest_rate_hike_2pct", "Rate +2%"),
            ("emergency_expense_5L", "Emergency ₹5L")
        ]
        for key, label in scenario_keys:
            s = all_scenarios.get(key, {})
            if s:
                names.append(label)
                buffers.append(s.get("buffer_months", 0))
                survivable.append(s.get("survivable", True))
                colors.append(severity_color_map.get(s.get("severity", "low"), "#22c55e"))

        return ScenarioComparisonData(
            scenario_names=names,
            buffer_months=buffers,
            survivable=survivable,
            severity_colors=colors
        )

    def _build_affordability_bar(self, blackboard: dict) -> AffordabilityBarData:
        financial_reality = blackboard.get("financial_reality", {})
        user_input = blackboard.get("user_input", {})
        return AffordabilityBarData(
            asked_price=user_input.get("property_price", 0),
            safe_price=financial_reality.get("safe_property_price", 0),
            maximum_price=financial_reality.get("maximum_property_price", 0)
        )

    def _build_risk_gauge(self, blackboard: dict) -> RiskGaugeData:
        risk_score = blackboard.get("risk_score", {})
        score = risk_score.get("composite_score", 50)
        label = risk_score.get("risk_label", "Moderate Risk")
        color_map = {
            "Safe": "#22c55e",
            "Moderate Risk": "#eab308",
            "High Risk": "#ef4444"
        }
        return RiskGaugeData(
            score=score,
            label=RiskLabel(label),
            color=color_map.get(label, "#eab308")
        )

    def _build_pdf_content(self, blackboard: dict, raw: dict) -> PDFContent:
        from datetime import datetime
        verdict = blackboard.get("verdict", {})
        user_input = blackboard.get("user_input", {})
        risk_score = blackboard.get("risk_score", {})
        all_scenarios = blackboard.get("all_scenarios", {})
        behavioral = blackboard.get("behavioral_analysis", {})

        return PDFContent(
            session_id=blackboard.get("session_id", ""),
            user_name="User",
            generated_at=datetime.now().isoformat(),
            risk_score_section=PDFSection(
                title="Risk Assessment",
                content=raw.get("formatted_risk_summary", "")
            ),
            scenario_section=PDFSection(
                title="Scenario Analysis",
                content="\n".join(
                    f"{k}: {v}"
                    for k, v in raw.get("scenario_explanations", {}).items()
                )
            ),
            cash_flow_section=PDFSection(
                title="Cash Flow Summary",
                content=f"Safe property price: {blackboard.get('financial_reality', {}).get('safe_property_price', 0)}"
            ),
            behavioral_section=PDFSection(
                title="Behavioral Analysis",
                content=raw.get("behavioral_summary", "")
            ),
            action_items_section=PDFSection(
                title="Recommended Actions",
                content="\n".join(verdict.get("suggested_actions", []))
                if isinstance(verdict, dict)
                else "\n".join(getattr(verdict, "suggested_actions", []))
            )
        )