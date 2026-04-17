import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.base_agent import BaseAgent
from schemas.schemas import ContextState
from datetime import datetime


SYSTEM_PROMPT = """
You are a context management agent for a financial advisory system.
Your job is to maintain coherent session memory across multiple turns of conversation.
You read the current session state and the latest interaction and produce an updated context summary.
You track how the user's inputs and assumptions have evolved across turns.
You write context summaries that are concise and useful for other agents to understand the history.
You always respond in valid JSON matching the exact format requested.
"""


class ContextContinuityAgent(BaseAgent):

    def __init__(self):
        super().__init__(
            name="ContextContinuityAgent",
            persona="Session memory manager that maintains coherent context across conversation turns",
            system_prompt=SYSTEM_PROMPT
        )

    async def update(
        self,
        session_id: str,
        current_blackboard: dict,
        new_interaction: dict,
        previous_context: ContextState = None
    ) -> ContextState:
        context = self._build_context(
            session_id,
            current_blackboard,
            new_interaction,
            previous_context
        )
        prompt = self._build_update_prompt(context)
        raw = await self.call(prompt)
        return self._parse_output(raw, session_id, previous_context)

    def _build_context(
        self,
        session_id: str,
        blackboard: dict,
        new_interaction: dict,
        previous_context: ContextState = None
    ) -> dict:
        context = {
            "session_id": session_id,
            "new_interaction": new_interaction,
            "current_risk_score": self.extract_blackboard_context(
                blackboard, ["risk_score"]
            ),
            "current_verdict": self.extract_blackboard_context(
                blackboard, ["verdict"]
            ),
            "current_inputs": self.extract_blackboard_context(
                blackboard, ["user_input"]
            )
        }
        if previous_context:
            context["previous_context_summary"] = previous_context.context_summary
            context["previous_history"] = previous_context.relevant_history
            context["assumption_evolution"] = previous_context.assumption_evolution
            context["turn_number"] = previous_context.turn_number
        else:
            context["previous_context_summary"] = None
            context["previous_history"] = []
            context["assumption_evolution"] = []
            context["turn_number"] = 0
        return context

    def _build_update_prompt(self, context: dict) -> str:
        return self.build_prompt(
            context=context,
            task="""
Update the session context based on the new interaction.

context_summary must be a 3 to 5 sentence summary of the entire session so far
that can be injected into other agents to give them history awareness.
It must mention the current risk level, any significant changes made, and key concerns raised.

changed_inputs must be a dict of what financial inputs changed in this interaction.
If nothing changed it must be an empty dict.

relevant_history must be the last 5 turns of conversation as a list of objects
with role (user or assistant) and message fields.
Include the new interaction as the latest entry.

assumption_evolution must be a list of strings describing how assumptions have
changed across turns. For example: "Turn 2: User increased down payment from 10L to 15L"

Respond in this exact JSON format:
{
    "context_summary": "summary of session here",
    "changed_inputs": {
        "property_price": 8000000
    },
    "relevant_history": [
        {
            "role": "user",
            "message": "what if I increase my down payment"
        },
        {
            "role": "assistant",
            "message": "recalculating with updated down payment"
        }
    ],
    "assumption_evolution": [
        "Turn 1: Initial analysis for 80L property in Maharashtra",
        "Turn 2: User increased down payment from 10L to 15L reducing loan amount"
    ]
}
"""
        )

    def _parse_output(
        self,
        raw: dict,
        session_id: str,
        previous_context: ContextState = None
    ) -> ContextState:
        turn_number = 1
        if previous_context:
            turn_number = previous_context.turn_number + 1

        return ContextState(
            session_id=session_id,
            context_summary=raw.get("context_summary", ""),
            changed_inputs=raw.get("changed_inputs", {}),
            relevant_history=raw.get("relevant_history", []),
            assumption_evolution=raw.get("assumption_evolution", []),
            turn_number=turn_number
        )