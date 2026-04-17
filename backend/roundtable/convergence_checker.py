import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base_agent import BaseAgent
from schemas.schemas import RoundSummary, AgentMessage, MessageType
from datetime import datetime


SYSTEM_PROMPT = """
You are a discussion convergence checker for a financial advisory roundtable.
Your job is to read the latest round of agent discussion and decide if the agents have reached
sufficient consensus to move to a final verdict, or if another round of discussion is needed.
You look for unresolved challenges, open questions, and whether agent positions are converging or diverging.
You are strict — you only declare convergence when the key issues have been addressed.
You always respond in valid JSON matching the exact format requested.
"""

# Maximum rounds before forcing convergence regardless of discussion state
MAX_ROUNDS = 4


class ConvergenceChecker(BaseAgent):

    def __init__(self):
        super().__init__(
            name="ConvergenceChecker",
            persona="Discussion moderator who decides when the roundtable has reached consensus",
            system_prompt=SYSTEM_PROMPT
        )

    async def check(
        self,
        blackboard_dict: dict,
        current_round: int,
        round_messages: list
    ) -> RoundSummary:
        # Force convergence at max rounds regardless of discussion state
        if current_round >= MAX_ROUNDS:
            return self._force_convergence(current_round, round_messages)

        context = self._build_context(
            blackboard_dict, current_round, round_messages
        )
        prompt = self._build_check_prompt(context)
        raw = await self.call(prompt)
        return self._parse_output(raw, current_round, round_messages)

    def _build_context(
        self,
        blackboard_dict: dict,
        current_round: int,
        round_messages: list
    ) -> dict:
        # Pass only what is needed to assess convergence
        return {
            "current_round": current_round,
            "max_rounds": MAX_ROUNDS,
            "round_messages": [
                {
                    "agent": m.agent if hasattr(m, 'agent') else m.get("agent"),
                    "message_type": m.message_type if hasattr(m, 'message_type') else m.get("message_type"),
                    "content": m.content if hasattr(m, 'content') else m.get("content"),
                    "directed_at": m.directed_at if hasattr(m, 'directed_at') else m.get("directed_at")
                }
                for m in round_messages
            ],
            "open_questions": blackboard_dict.get("open_questions", []),
            "active_flags": blackboard_dict.get("active_flags", []),
            "previous_round_summaries": [
                {
                    "round": s.round_number if hasattr(s, 'round_number') else s.get("round_number"),
                    "productive": s.productive if hasattr(s, 'productive') else s.get("productive"),
                    "open_questions": s.open_questions if hasattr(s, 'open_questions') else s.get("open_questions", [])
                }
                for s in blackboard_dict.get("round_summaries", [])
            ]
        }

    def _build_check_prompt(self, context: dict) -> str:
        return self.build_prompt(
            context=context,
            task="""
Read the latest round of discussion messages and decide if the roundtable has converged.

Convergence means:
- All direct challenges between agents have been responded to
- No critical open questions remain unanswered
- Agent positions are moving toward agreement not further apart
- The key risk factors have been identified and discussed

converged must be true if consensus is sufficient, false if another round is needed
productive must be true if this round generated new useful information
open_questions must list any questions raised in this round that remain unanswered
conflicts_identified must list any new contradictions surfaced in this round
summary must be one sentence describing what this round accomplished

Respond in this exact JSON format:
{
    "converged": false,
    "productive": true,
    "open_questions": [
        "Has the user considered the impact of property maintenance costs?"
    ],
    "conflicts_identified": [
        "Aryan believes EMI ratio is acceptable but Priya flagged job loss scenario as critical"
    ],
    "summary": "Round identified key risk in job loss scenario with unresolved question about maintenance costs"
}
"""
        )

    def _parse_output(
        self,
        raw: dict,
        current_round: int,
        round_messages: list
    ) -> RoundSummary:
        messages = []
        for m in round_messages:
            if hasattr(m, 'agent'):
                messages.append(m)
            else:
                messages.append(AgentMessage(
                    agent=m.get("agent", ""),
                    message_type=MessageType(m.get("message_type", "observation")),
                    content=m.get("content", ""),
                    round=current_round,
                    timestamp=datetime.now().isoformat(),
                    directed_at=m.get("directed_at")
                ))

        summary = RoundSummary(
            round_number=current_round,
            messages=messages,
            productive=raw.get("productive", True),
            open_questions=raw.get("open_questions", []),
            conflicts_identified=raw.get("conflicts_identified", [])
        )

        # Set convergence flag on the summary object for orchestrator to read
        summary.__dict__["converged"] = raw.get("converged", False)
        return summary

    def _force_convergence(
        self,
        current_round: int,
        round_messages: list
    ) -> RoundSummary:
        # Called when max rounds is reached
        # Forces convergence so synthesizer can fire
        messages = []
        for m in round_messages:
            if hasattr(m, 'agent'):
                messages.append(m)
            else:
                messages.append(AgentMessage(
                    agent=m.get("agent", ""),
                    message_type=MessageType(m.get("message_type", "observation")),
                    content=m.get("content", ""),
                    round=current_round,
                    timestamp=datetime.now().isoformat(),
                    directed_at=m.get("directed_at")
                ))

        summary = RoundSummary(
            round_number=current_round,
            messages=messages,
            productive=True,
            open_questions=[],
            conflicts_identified=[]
        )
        summary.__dict__["converged"] = True
        return summary