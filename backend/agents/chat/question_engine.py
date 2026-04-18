"""
question_engine.py — Deterministic question sequencing and progress tracking.

This module handles the rule-based logic around what to ask next,
how to detect if the user is stuck, and how to handle edge cases
in the conversation flow that the LLM should not decide.

Why this exists separately from IntakeAgent:
    IntakeAgent uses the LLM to generate natural-sounding questions.
    QuestionEngine is pure Python logic — it tracks state, detects
    loops, handles skips, and enforces the sequence without any
    LLM involvement. Separating these keeps IntakeAgent focused on
    language and QuestionEngine focused on flow control.

Used by: orchestrator.py
"""

from dataclasses import dataclass, field
from typing import Optional
from agents.chat.intake_agent import CollectedData, QUESTION_SEQUENCE, REQUIRED_FIELDS


# ─── How many times we'll re-ask a field before skipping it ───────────────────
MAX_ATTEMPTS_PER_FIELD = 3

# ─── Fields the user is allowed to skip ───────────────────────────────────────
# Required fields cannot be skipped — analysis won't run without them.
# Optional fields can be skipped after MAX_ATTEMPTS_PER_FIELD tries.
SKIPPABLE_FIELDS = {
    "facing",
    "floor_number",
    "parking_included",
    "parking_cost",
    "builder_name",
    "project_name",
    "rera_number",
    "first_time_buyer",
    "owner_gender",
    "existing_loan_emi",
}

# ─── Default values used when an optional field is skipped ────────────────────
SKIP_DEFAULTS = {
    "facing":           "internal",
    "floor_number":     5,
    "parking_included": False,
    "parking_cost":     300000.0,   # ₹3L conservative default
    "first_time_buyer": True,
    "owner_gender":     "male",
    "existing_loan_emi": 0.0,
    "tenure_years":     20,
    "annual_interest_rate": 0.0875,  # 8.75% current average
    "monthly_expenses": None,        # calculated from income if missing
}

# ─── Skip triggers — if user says these we skip the current field ──────────────
SKIP_PHRASES = {
    "skip", "don't know", "dont know", "not sure", "no idea",
    "skip this", "move on", "next", "pata nahi", "nahi pata",
    "skip karo", "aage badho", "ignore"
}


@dataclass
class QuestionState:
    """Tracks the state of the question flow for one session."""
    session_id:             str
    attempts_per_field:     dict = field(default_factory=dict)
    skipped_fields:         list = field(default_factory=list)
    current_field:          Optional[str] = None
    total_questions_asked:  int = 0
    conversation_started:   bool = False


class QuestionEngine:

    def __init__(self):
        # One QuestionState per session, keyed by session_id
        self._states: dict[str, QuestionState] = {}

    # -------------------------------------------------------------------------
    # Session management
    # -------------------------------------------------------------------------

    def get_or_create_state(self, session_id: str) -> QuestionState:
        if session_id not in self._states:
            self._states[session_id] = QuestionState(session_id=session_id)
        return self._states[session_id]

    def clear_session(self, session_id: str):
        if session_id in self._states:
            del self._states[session_id]

    # -------------------------------------------------------------------------
    # Core method — called before IntakeAgent to handle edge cases
    # -------------------------------------------------------------------------

    def pre_process(
        self,
        session_id:    str,
        user_message:  str,
        collected:     CollectedData
    ) -> dict:
        """
        Run before IntakeAgent.process_message() on every user message.

        Returns:
            should_skip_llm:  bool — True if we can respond without LLM
            override_message: str  — message to send if skipping LLM
            updated_collected: CollectedData — with defaults applied if skipped
            field_was_skipped: bool
        """
        state = self.get_or_create_state(session_id)

        # Track current field
        current_field = collected.next_question_field()
        state.current_field = current_field

        # ── Handle skip intent ────────────────────────────────────────────────
        if self._is_skip_intent(user_message):
            if current_field and current_field in SKIPPABLE_FIELDS:
                updated = self._apply_skip_default(collected, current_field)
                state.skipped_fields.append(current_field)

                next_field_after_skip = updated.next_question_field()
                next_q = self._get_question_text(next_field_after_skip)

                return {
                    "should_skip_llm":   True,
                    "override_message":  (
                        f"No problem, I'll use a standard estimate for that. "
                        f"\n\n{next_q}"
                    ),
                    "updated_collected": updated,
                    "field_was_skipped": True,
                }
            elif current_field in REQUIRED_FIELDS:
                return {
                    "should_skip_llm":   True,
                    "override_message":  (
                        f"I understand, but I need this information to run "
                        f"the analysis. Without it I can't calculate your "
                        f"affordability accurately. "
                        f"Could you give me an approximate figure?"
                    ),
                    "updated_collected": collected,
                    "field_was_skipped": False,
                }

        # ── Track attempts per field ──────────────────────────────────────────
        if current_field:
            attempts = state.attempts_per_field.get(current_field, 0)
            state.attempts_per_field[current_field] = attempts + 1

            # Auto-skip optional field after too many failed attempts
            if (
                attempts >= MAX_ATTEMPTS_PER_FIELD
                and current_field in SKIPPABLE_FIELDS
            ):
                updated = self._apply_skip_default(collected, current_field)
                state.skipped_fields.append(current_field)
                print(
                    f"[QuestionEngine] Auto-skipping {current_field} "
                    f"after {attempts} attempts"
                )
                return {
                    "should_skip_llm":   False,  # still use LLM for message
                    "override_message":  "",
                    "updated_collected": updated,
                    "field_was_skipped": True,
                }

        state.total_questions_asked += 1

        return {
            "should_skip_llm":   False,
            "override_message":  "",
            "updated_collected": collected,
            "field_was_skipped": False,
        }

    # -------------------------------------------------------------------------
    # Progress reporting — shown in the chat UI
    # -------------------------------------------------------------------------

    def get_progress(
        self,
        session_id: str,
        collected:  CollectedData
    ) -> dict:
        """
        Returns progress data for the frontend progress bar.
        """
        state         = self.get_or_create_state(session_id)
        missing       = collected.missing_required()
        next_field    = collected.next_question_field()

        return {
            "completion_pct":       collected.completion_pct(),
            "required_remaining":   len(missing),
            "required_total":       len(REQUIRED_FIELDS),
            "fields_collected":     len(collected.to_dict()),
            "skipped_fields":       state.skipped_fields,
            "current_field":        next_field,
            "is_ready":             collected.is_ready(),
            "questions_asked":      state.total_questions_asked,
        }

    # -------------------------------------------------------------------------
    # Opening message — first thing shown when chat starts
    # -------------------------------------------------------------------------

    def get_opening_message(self) -> str:
        return (
            "Hi! I'm NIV — your Mumbai property advisor.\n\n"
            "I'll help you figure out the real cost of buying this home, "
            "whether you can actually afford it, and what risks you should "
            "know about before signing anything.\n\n"
            "Tell me about the property you're looking at — "
            "where is it, what's the price, or anything else you know so far. "
            "We'll take it one step at a time."
        )

    # -------------------------------------------------------------------------
    # Analysis trigger message — shown when ready
    # -------------------------------------------------------------------------

    def get_analysis_message(self, collected: CollectedData) -> str:
        price_str = (
            f"₹{collected.property_price/1e5:.1f}L"
            if collected.property_price
            else "your property"
        )
        locality_str = (
            f" in {collected.locality.title()}"
            if collected.locality
            else ""
        )
        return (
            f"Perfect — I have everything I need.\n\n"
            f"Running a full analysis on {price_str}{locality_str} now. "
            f"This includes:\n"
            f"• True cost breakdown (all hidden charges)\n"
            f"• EMI and affordability check\n"
            f"• 5 financial stress scenarios\n"
            f"• Risk score\n"
            f"• AI expert roundtable discussion\n"
            f"• Complete audit report you can download\n\n"
            f"Give me about 30-60 seconds..."
        )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _is_skip_intent(self, message: str) -> bool:
        """Check if the user's message is a skip request."""
        return message.lower().strip() in SKIP_PHRASES

    def _apply_skip_default(
        self,
        collected: CollectedData,
        field_name: str
    ) -> CollectedData:
        """Apply the default value for a skipped field."""
        import copy
        updated = copy.copy(collected)
        default = SKIP_DEFAULTS.get(field_name)
        if default is not None:
            setattr(updated, field_name, default)
        return updated

    def _get_question_text(self, field_name: Optional[str]) -> str:
        """Get the question text for a given field name."""
        if not field_name:
            return ""
        for fname, fq in QUESTION_SEQUENCE:
            if fname == field_name:
                return fq
        return ""

    # -------------------------------------------------------------------------
    # Apply all defaults for missing optional fields before analysis
    # -------------------------------------------------------------------------

    def apply_analysis_defaults(self, collected: CollectedData) -> CollectedData:
        """
        Before triggering the analysis pipeline, fill in any missing
        optional fields with sensible defaults so no downstream
        calculation receives a None where it expects a number.

        Called by orchestrator right before running the pipeline.
        """
        import copy
        final = copy.copy(collected)

        # Tenure: cap at (60 - age) years, default 20
        if final.tenure_years is None:
            if final.age:
                final.tenure_years = min(20, max(5, 60 - final.age))
            else:
                final.tenure_years = 20

        # Interest rate: current Mumbai average
        if final.annual_interest_rate is None:
            final.annual_interest_rate = 0.0875

        # Monthly expenses: if not given, estimate 40% of income
        if final.monthly_expenses is None and final.monthly_income:
            final.monthly_expenses = final.monthly_income * 0.40

        # Floor number default
        if final.floor_number is None:
            final.floor_number = 5

        # Facing default
        if final.facing is None:
            final.facing = "internal"

        # Parking default
        if final.parking_included is None:
            final.parking_included = False
        if final.parking_cost is None:
            final.parking_cost = 300000.0

        # Owner gender default
        if final.owner_gender is None:
            final.owner_gender = "male"

        # First time buyer default
        if final.first_time_buyer is None:
            final.first_time_buyer = True

        # Existing loan EMI default
        if final.existing_loan_emi is None:
            final.existing_loan_emi = 0.0

        return final