import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
from datetime import datetime
from typing import Optional
from fastapi import WebSocket

from agents.base_agent import BaseAgent
from roundtable.blackboard import Blackboard
from roundtable.convergence_checker import ConvergenceChecker
from schemas.schemas import AgentMessage, MessageType


MARCUS_SYSTEM_PROMPT = """
You are Marcus, a sharp financial analyst who has spent 15 years stress testing home loan decisions for Indian families.
You speak in specifics — actual numbers, actual ratios, actual months. Never vague.
You get uncomfortable when people gloss over EMI ratios or assume income stability without evidence.
You push back hard when assumptions look optimistic and you do not give in without strong counter evidence.
You always reference the exact numbers from the analysis in your messages.
You address Zara and Soren by name when responding to their specific points.
You change your position when evidence is strong but you make people earn it.
Your messages are direct, 2 to 4 sentences, no fluff.
You always respond in valid JSON matching the exact format requested.
"""

ZARA_SYSTEM_PROMPT = """
You are Zara, a risk strategist who specializes in finding what breaks first in a financial plan.
You are always thinking three steps ahead toward the worst case.
You ask what if constantly and you are never satisfied until every stress scenario has been examined.
You get increasingly blunt when the financial picture is genuinely dangerous.
You are especially sharp about job loss risk, medical emergencies, interest rate spikes, and market downturns.
You address Marcus and Soren by name when building on or challenging their points.
When Marcus says something is fine you are the one who asks what happens when it is not.
Your messages are sharp, 2 to 4 sentences, always ending on the risk that has not been addressed yet.
You always respond in valid JSON matching the exact format requested.
"""

SOREN_SYSTEM_PROMPT = """
You are Soren, a behavioral economist who reads the psychological patterns behind financial decisions.
You are calm, measured, and you often speak last in a round — but when you do the conversation shifts.
You connect the behavioral flags directly to the financial risk being discussed by Marcus and Zara.
You are the one who says things like — before we move on I want to flag something about how this person described their situation.
You never moralize. You observe and connect patterns to consequences.
You address Marcus and Zara by name when your behavioral observations are directly relevant to their points.
Your messages feel like a realization, not a lecture. 2 to 4 sentences, calm and precise.
You always respond in valid JSON matching the exact format requested.
"""

ROUND_1_TASK = """
This is Round 1. Give your opening observation about this financial situation.
Focus on the single most important thing you see in the data from your perspective.
Be specific. Reference actual numbers.

Respond in this exact JSON format:
{
    "message_type": "observation",
    "content": "your opening observation here",
    "directed_at": null
}
"""

ROUND_N_TASK = """
This is Round {round_number}. You have read what the other agents said this round.
Respond to the most important point raised. You can agree, challenge, revise your position, or raise a new concern.
Address the agent you are responding to by name.
If you are challenging something, be specific about why.
If you are agreeing, add something new to the point.

Respond in this exact JSON format:
{
    "message_type": "challenge",
    "content": "your response here referencing the other agent by name",
    "directed_at": "Marcus"
}
"""


class RoundtableAgent(BaseAgent):

    def __init__(self, name: str, system_prompt: str):
        super().__init__(
            name=name,
            persona=f"Roundtable discussion agent {name}",
            system_prompt=system_prompt
        )

    async def generate_message(
        self,
        blackboard_context: dict,
        round_number: int,
        previous_messages: list,
        task: str
    ) -> AgentMessage:
        context = {
            "financial_data": {
                "financial_reality": blackboard_context.get("financial_reality"),
                "all_scenarios": blackboard_context.get("all_scenarios"),
                "risk_score": blackboard_context.get("risk_score")
            },
            "behavioral_flags": blackboard_context.get("behavioral_analysis"),
            "validation_conflicts": blackboard_context.get("validation"),
            "round_number": round_number,
            "your_name": self.name,
            "previous_messages_this_round": [
                {
                    "agent": m.agent if hasattr(m, "agent") else m.get("agent"),
                    "message_type": str(m.message_type) if hasattr(m, "message_type") else m.get("message_type"),
                    "content": m.content if hasattr(m, "content") else m.get("content")
                }
                for m in previous_messages
            ],
            "open_questions": blackboard_context.get("open_questions", []),
            "active_flags": blackboard_context.get("active_flags", [])
        }

        prompt = self.build_prompt(context=context, task=task)
        raw = await self.call(prompt)
        return self._parse_message(raw, round_number)

    def _parse_message(self, raw: dict, round_number: int) -> AgentMessage:
        return AgentMessage(
            agent=self.name,
            message_type=MessageType(raw.get("message_type", "observation")),
            content=raw.get("content", ""),
            round=round_number,
            timestamp=datetime.now().isoformat(),
            directed_at=raw.get("directed_at")
        )


class DiscussionEngine:

    def __init__(self):
        self.marcus = RoundtableAgent("Marcus", MARCUS_SYSTEM_PROMPT)
        self.zara = RoundtableAgent("Zara", ZARA_SYSTEM_PROMPT)
        self.soren = RoundtableAgent("Soren", SOREN_SYSTEM_PROMPT)
        self.agents = [self.marcus, self.zara, self.soren]
        self.convergence_checker = ConvergenceChecker()

    async def run(
        self,
        blackboard: Blackboard,
        websocket: WebSocket
    ) -> bool:
        # Runs the full roundtable discussion
        # Streams every message through the websocket as it is generated
        # Returns True when converged

        await self._stream_event(websocket, {
            "type": "roundtable_start",
            "agents": ["Marcus", "Zara", "Soren"]
        })

        converged = False

        while not converged:
            blackboard.increment_round()
            current_round = blackboard.state.current_round

            await self._stream_event(websocket, {
                "type": "round_start",
                "round": current_round
            })

            # Determine task for this round
            if current_round == 1:
                task = ROUND_1_TASK
            else:
                task = ROUND_N_TASK.replace("{round_number}", str(current_round))

            # Get blackboard context for agents
            blackboard_context = blackboard.get_context_for_agent([
                "financial_reality",
                "all_scenarios",
                "risk_score",
                "behavioral_analysis",
                "validation",
                "open_questions",
                "active_flags"
            ])

            # Run all three agents in parallel for round 1
            # For subsequent rounds agents react to previous messages sequentially
            if current_round == 1:
                messages = await self._run_parallel_round(
                    blackboard_context, current_round, [], task, websocket
                )
            else:
                previous_round_messages = blackboard.get_messages_for_round(
                    current_round - 1
                )
                messages = await self._run_sequential_round(
                    blackboard_context, current_round,
                    previous_round_messages, task, websocket
                )

            # Add all messages to blackboard
            for msg in messages:
                blackboard.add_agent_message(msg)

            # Check convergence
            round_summary = await self.convergence_checker.check(
                blackboard.get_state_as_dict(),
                current_round,
                messages
            )

            blackboard.add_round_summary(round_summary)

            # Add open questions from this round to blackboard
            for question in round_summary.open_questions:
                blackboard.add_open_question(question)

            converged = round_summary.__dict__.get("converged", False)

            await self._stream_event(websocket, {
                "type": "round_end",
                "round": current_round,
                "summary": round_summary.open_questions,
                "converged": converged
            })

        blackboard.mark_converged()

        await self._stream_event(websocket, {
            "type": "convergence",
            "status": "converged",
            "rounds_completed": blackboard.state.current_round
        })

        return True

    async def _run_parallel_round(
        self,
        blackboard_context: dict,
        round_number: int,
        previous_messages: list,
        task: str,
        websocket: WebSocket
    ) -> list:
        # All agents generate messages simultaneously
        # Stream each as it arrives
        tasks = [
            agent.generate_message(
                blackboard_context, round_number, previous_messages, task
            )
            for agent in self.agents
        ]

        messages = []
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                continue
            messages.append(result)
            await self._stream_message(websocket, result)

        return messages

    async def _run_sequential_round(
        self,
        blackboard_context: dict,
        round_number: int,
        previous_messages: list,
        task: str,
        websocket: WebSocket
    ) -> list:
        # Agents generate messages one at a time
        # Each agent sees what the previous agents said in this round
        # Soren always goes last so he can respond to both Marcus and Zara
        messages = []
        current_round_messages = []

        for agent in [self.marcus, self.zara, self.soren]:
            await self._stream_event(websocket, {
                "type": "agent_typing",
                "agent": agent.name
            })

            context_with_current = blackboard_context.copy()
            message = await agent.generate_message(
                context_with_current,
                round_number,
                previous_messages + current_round_messages,
                task
            )

            current_round_messages.append(message)
            messages.append(message)
            await self._stream_message(websocket, message)

        return messages

    async def _stream_message(
        self,
        websocket: WebSocket,
        message: AgentMessage
    ):
        await websocket.send_text(json.dumps({
            "type": "agent_message",
            "agent": message.agent,
            "message_type": str(message.message_type.value) if hasattr(message.message_type, 'value') else str(message.message_type),
            "content": message.content,
            "round": message.round,
            "timestamp": message.timestamp,
            "directed_at": message.directed_at
        }))

    async def _stream_event(
        self,
        websocket: WebSocket,
        event: dict
    ):
        await websocket.send_text(json.dumps(event))