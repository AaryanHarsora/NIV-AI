import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import asyncio
from fastapi import WebSocket
from datetime import datetime

from roundtable.blackboard import Blackboard
from roundtable.discussion_engine import DiscussionEngine
from agents.ai_reasoning.behavioral_analysis import BehavioralAnalysisAgent
from agents.ai_reasoning.decision_synthesizer import DecisionSynthesizerAgent
from agents.context_interaction.conversation import ConversationAgent
from agents.context_interaction.context_continuity import ContextContinuityAgent
from agents.presentation.presentation import PresentationAgent
from agents.validation.validation import ValidationAgent
from schemas.schemas import (
    VerdictOutput, ConversationOutput, AnalysisResponse,
    UserInput, BehavioralIntake
)


class Orchestrator:
    # Central execution controller
    # This is the only class Dev 1's main.py calls into from the AI layer
    # Exposes three public methods: analyze, continue_conversation, run_roundtable

    def __init__(self):
        self.behavioral_agent = BehavioralAnalysisAgent()
        self.synthesizer_agent = DecisionSynthesizerAgent()
        self.conversation_agent = ConversationAgent()
        self.context_agent = ContextContinuityAgent()
        self.presentation_agent = PresentationAgent()
        self.validation_agent = ValidationAgent()
        self.discussion_engine = DiscussionEngine()

        # In memory store for active blackboards keyed by session_id
        # One blackboard per active session
        self._blackboards: dict[str, Blackboard] = {}

        # In memory store for context states keyed by session_id
        self._context_states: dict = {}

    def _get_or_create_blackboard(self, session_id: str) -> Blackboard:
        if session_id not in self._blackboards:
            self._blackboards[session_id] = Blackboard(session_id)
        return self._blackboards[session_id]

    async def analyze(
        self,
        session_id: str,
        user_input: UserInput,
        behavioral_intake: BehavioralIntake,
        deterministic_results: dict
    ) -> AnalysisResponse:
        # Full analysis pipeline for a new analysis
        # Called by Dev 1's POST /analyze route
        # deterministic_results contains outputs from Dev 1's three deterministic agents

        blackboard = self._get_or_create_blackboard(session_id)

        # Load everything onto the blackboard
        blackboard.set_user_input(user_input)
        blackboard.set_behavioral_intake(behavioral_intake)

        # Load deterministic results from Dev 1 onto blackboard
        if deterministic_results.get("india_cost_breakdown"):
            from schemas.schemas import IndiaCostBreakdown
            blackboard.set_india_cost_breakdown(
                IndiaCostBreakdown(**deterministic_results["india_cost_breakdown"])
            )

        if deterministic_results.get("financial_reality"):
            from schemas.schemas import FinancialRealityOutput
            blackboard.set_financial_reality(
                FinancialRealityOutput(**deterministic_results["financial_reality"])
            )

        if deterministic_results.get("all_scenarios"):
            from schemas.schemas import AllScenariosOutput
            blackboard.set_all_scenarios(
                AllScenariosOutput(**deterministic_results["all_scenarios"])
            )

        if deterministic_results.get("risk_score"):
            from schemas.schemas import RiskScoreOutput
            blackboard.set_risk_score(
                RiskScoreOutput(**deterministic_results["risk_score"])
            )

        # Run behavioral analysis and validation in parallel
        behavioral_result, validation_result = await asyncio.gather(
            self.behavioral_agent.analyze(
                behavioral_answers=[a.model_dump() for a in behavioral_intake.answers],
                financial_inputs=user_input.model_dump(),
                india_cost_breakdown=deterministic_results.get("india_cost_breakdown", {})
            ),
            self.validation_agent.validate(
                blackboard.get_state_as_dict()
            )
        )

        blackboard.set_behavioral_analysis(behavioral_result)
        blackboard.set_validation(validation_result)

        # Add behavioral flags to blackboard active flags
        for flag in behavioral_result.bias_flags:
            blackboard.add_flag(
                f"{flag.bias_type.value} bias detected: {flag.evidence[:50]}"
            )

        # Add validation conflicts to blackboard
        for conflict in validation_result.conflicts:
            blackboard.add_flag(
                f"Conflict: {conflict.description[:50]}"
            )

        # Run presentation agent
        presentation_result = await self.presentation_agent.present(
            blackboard.get_state_as_dict()
        )
        blackboard.set_presentation(presentation_result)

        # Update context state
        context_state = await self.context_agent.update(
            session_id=session_id,
            current_blackboard=blackboard.get_state_as_dict(),
            new_interaction={
                "role": "user",
                "message": "Initial analysis submitted",
                "inputs": user_input.model_dump()
            },
            previous_context=self._context_states.get(session_id)
        )
        self._context_states[session_id] = context_state

        return self._build_analysis_response(blackboard)

    async def run_roundtable(
        self,
        session_id: str,
        websocket: WebSocket
    ) -> None:
        # Runs the live roundtable discussion and streams to websocket
        # Called by Dev 1's WebSocket /roundtable/{session_id} endpoint
        # analyze must be called before run_roundtable

        blackboard = self._get_or_create_blackboard(session_id)

        if not blackboard.state.financial_reality:
            await websocket.send_text(
                '{"type": "error", "message": "Analysis must be run before roundtable", "recoverable": false}'
            )
            return

        # Run the discussion engine
        await self.discussion_engine.run(blackboard, websocket)

        # Once converged run the synthesizer
        verdict = await self.synthesizer_agent.synthesize(
            blackboard.get_state_as_dict()
        )
        blackboard.set_verdict(verdict)

        # Stream verdict to frontend
        import json
        await websocket.send_text(json.dumps({
            "type": "verdict_ready",
            "data": verdict.model_dump()
        }))

        # Save verdict to Firestore via Dev 1's firestore ops
        try:
            from firebase.firestore_ops import save_verdict
            await asyncio.to_thread(
                save_verdict, session_id, verdict.model_dump()
            )
        except Exception as e:
            print(f"Firestore save failed: {e}")

    async def continue_conversation(
        self,
        session_id: str,
        message: str
    ) -> ConversationOutput:
        # Handles a follow up turn in the conversation
        # Called by Dev 1's POST /conversation/{session_id} route

        blackboard = self._get_or_create_blackboard(session_id)

        # Parse the user message
        conversation_output = await self.conversation_agent.parse(
            message=message,
            current_blackboard=blackboard.get_state_as_dict()
        )

        # If there are extracted variables update the blackboard inputs
        if conversation_output.extracted_variables:
            current_input = blackboard.state.user_input
            if current_input:
                updated_data = current_input.model_dump()
                updated_data.update(conversation_output.extracted_variables)
                from schemas.schemas import UserInput
                blackboard.set_user_input(UserInput(**updated_data))

        # Update context state
        context_state = await self.context_agent.update(
            session_id=session_id,
            current_blackboard=blackboard.get_state_as_dict(),
            new_interaction={
                "role": "user",
                "message": message
            },
            previous_context=self._context_states.get(session_id)
        )
        self._context_states[session_id] = context_state

        return conversation_output

    def _build_analysis_response(self, blackboard: Blackboard) -> AnalysisResponse:
        state = blackboard.state
        return AnalysisResponse(
            session_id=blackboard.session_id,
            financial_reality=state.financial_reality,
            all_scenarios=state.all_scenarios,
            risk_score=state.risk_score,
            behavioral_analysis=state.behavioral_analysis,
            validation=state.validation,
            presentation=state.presentation,
            verdict=state.verdict or VerdictOutput(
                verdict="wait",
                confidence=0,
                primary_reasons=[],
                key_warnings=[],
                safe_price_recommendation=0,
                suggested_actions=[],
                unresolved_conflicts=[],
                final_narrative="Roundtable discussion pending"
            )
        )

    def clear_session(self, session_id: str):
        # Clears session data from memory
        # Called when session is completed or expired
        if session_id in self._blackboards:
            del self._blackboards[session_id]
        if session_id in self._context_states:
            del self._context_states[session_id]