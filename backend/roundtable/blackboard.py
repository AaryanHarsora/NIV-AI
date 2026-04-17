import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas.schemas import (
    BlackboardState, AgentMessage, RoundSummary,
    UserInput, BehavioralIntake, IndiaCostBreakdown,
    FinancialRealityOutput, AllScenariosOutput, RiskScoreOutput,
    BehavioralAnalysisOutput, ValidationOutput, PresentationOutput,
    VerdictOutput, ContextState
)
from datetime import datetime
from typing import Optional


class Blackboard:
    # Shared context object all agents read from and write to
    # This is the single source of truth for everything in one analysis session
    # It is initialized once per analysis and passed by reference to every agent

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.state = BlackboardState(session_id=session_id)

    def set_user_input(self, user_input: UserInput):
        self.state.user_input = user_input

    def set_behavioral_intake(self, intake: BehavioralIntake):
        self.state.behavioral_intake = intake

    def set_india_cost_breakdown(self, breakdown: IndiaCostBreakdown):
        self.state.india_cost_breakdown = breakdown

    def set_financial_reality(self, result: FinancialRealityOutput):
        self.state.financial_reality = result

    def set_all_scenarios(self, result: AllScenariosOutput):
        self.state.all_scenarios = result

    def set_risk_score(self, result: RiskScoreOutput):
        self.state.risk_score = result

    def set_behavioral_analysis(self, result: BehavioralAnalysisOutput):
        self.state.behavioral_analysis = result

    def set_validation(self, result: ValidationOutput):
        self.state.validation = result

    def set_presentation(self, result: PresentationOutput):
        self.state.presentation = result

    def set_verdict(self, result: VerdictOutput):
        self.state.verdict = result

    def add_agent_message(self, message: AgentMessage):
        # Adds a message to the discussion transcript
        self.state.discussion_transcript.append(message)

    def add_round_summary(self, summary: RoundSummary):
        self.state.round_summaries.append(summary)

    def add_flag(self, flag: str):
        # Adds a flag raised by any agent during discussion
        if flag not in self.state.active_flags:
            self.state.active_flags.append(flag)

    def add_open_question(self, question: str):
        # Adds an unresolved question to the open questions list
        if question not in self.state.open_questions:
            self.state.open_questions.append(question)

    def resolve_question(self, question: str):
        # Removes a question from open questions when resolved
        if question in self.state.open_questions:
            self.state.open_questions.remove(question)

    def increment_round(self):
        self.state.current_round += 1

    def mark_converged(self):
        self.state.converged = True

    def get_state_as_dict(self) -> dict:
        # Returns the full blackboard state as a plain dict
        # Used when passing context to agents
        return self.state.model_dump()

    def get_messages_for_round(self, round_number: int) -> list:
        # Returns all messages from a specific round
        return [
            m for m in self.state.discussion_transcript
            if m.round == round_number
        ]

    def get_latest_round_messages(self) -> list:
        # Returns all messages from the current round
        return self.get_messages_for_round(self.state.current_round)

    def get_full_transcript_as_text(self) -> str:
        # Returns the full discussion transcript as readable text
        # Used by the synthesizer to read the entire discussion
        lines = []
        for msg in self.state.discussion_transcript:
            lines.append(
                f"[Round {msg.round}] {msg.agent} ({msg.message_type}): {msg.content}"
            )
        return "\n".join(lines)

    def get_context_for_agent(self, agent_keys: list) -> dict:
        # Returns only the blackboard sections an agent needs
        # Keeps prompts token-efficient
        full = self.get_state_as_dict()
        context = {k: full.get(k) for k in agent_keys if full.get(k) is not None}
        context["session_id"] = self.session_id
        context["current_round"] = self.state.current_round
        context["open_questions"] = self.state.open_questions
        context["active_flags"] = self.state.active_flags
        return context

    def is_ready_for_synthesis(self) -> bool:
        # Checks all required fields are populated before synthesizer fires
        return all([
            self.state.financial_reality is not None,
            self.state.all_scenarios is not None,
            self.state.risk_score is not None,
            self.state.behavioral_analysis is not None,
            self.state.validation is not None,
            self.state.converged
        ])