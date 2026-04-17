import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.base_agent import BaseAgent
from schemas.schemas import ConversationOutput, ConversationIntent


SYSTEM_PROMPT = """
You are a conversation parsing agent for a financial advisory system.
Your job is to read a user's natural language message and extract structured information from it.
You identify what the user wants to do, what financial values they want to change, and which agents need to rerun.
You never provide financial advice yourself.
You only parse intent and extract variables.
You always respond in valid JSON matching the exact format requested.
"""


AGENTS_THAT_CAN_RERUN = [
    "financial_reality",
    "scenario_simulation",
    "risk_scorer",
    "behavioral_analysis",
    "decision_synthesizer",
    "validation",
    "presentation"
]


class ConversationAgent(BaseAgent):

    def __init__(self):
        super().__init__(
            name="ConversationAgent",
            persona="Conversation parser that extracts intent and variables from user messages",
            system_prompt=SYSTEM_PROMPT
        )

    async def parse(
        self,
        message: str,
        current_blackboard: dict
    ) -> ConversationOutput:
        context = self._build_context(message, current_blackboard)
        prompt = self._build_parse_prompt(context)
        raw = await self.call(prompt)
        return self._parse_output(raw)

    def _build_context(self, message: str, blackboard: dict) -> dict:
        # Only pass current inputs and risk score so agent understands current state
        return {
            "user_message": message,
            "current_inputs": self.extract_blackboard_context(
                blackboard, ["user_input", "risk_score"]
            ),
            "available_agents_to_trigger": AGENTS_THAT_CAN_RERUN
        }

    def _build_parse_prompt(self, context: dict) -> str:
        return self.build_prompt(
            context=context,
            task="""
Parse the user message and extract structured information.

intent must be one of:
- new_analysis: user wants to start a completely fresh analysis
- update_input: user wants to change one or more financial inputs
- ask_question: user is asking a question about their results
- compare: user wants to compare two scenarios
- export: user wants to download their report

extracted_variables must contain any financial values mentioned in the message
as key value pairs matching the UserInput field names:
monthly_income, monthly_expenses, total_savings, down_payment,
property_price, tenure_years, annual_interest_rate, age, state

trigger_agents must list which agents need to rerun based on what changed.
If property_price or down_payment changed trigger all agents.
If only tenure_years or annual_interest_rate changed trigger financial_reality, scenario_simulation, risk_scorer, validation, presentation, decision_synthesizer.
If no inputs changed and user is asking a question trigger only presentation.

follow_up_question must be a clarifying question if the message is ambiguous, null otherwise.
response_to_user must be a short friendly acknowledgment of what you understood.

Respond in this exact JSON format:
{
    "structured_input": {},
    "intent": "update_input",
    "extracted_variables": {
        "property_price": 7500000
    },
    "follow_up_question": null,
    "trigger_agents": [
        "financial_reality",
        "scenario_simulation",
        "risk_scorer",
        "validation",
        "presentation",
        "decision_synthesizer"
    ],
    "response_to_user": "Got it. Recalculating with a property price of ₹75 lakhs."
}
"""
        )

    def _parse_output(self, raw: dict) -> ConversationOutput:
        return ConversationOutput(
            structured_input=raw.get("structured_input", {}),
            intent=ConversationIntent(raw.get("intent", "ask_question")),
            extracted_variables=raw.get("extracted_variables", {}),
            follow_up_question=raw.get("follow_up_question"),
            trigger_agents=raw.get("trigger_agents", []),
            response_to_user=raw.get("response_to_user", "")
        )