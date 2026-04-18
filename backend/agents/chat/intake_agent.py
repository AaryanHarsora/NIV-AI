"""
IntakeAgent — Extracts structured property and financial data
from natural conversation.

Flow:
    1. User sends a message (could be anything — "I'm looking at a 2BHK
       in Powai for 1.2 crore" or just "hi")
    2. extract() parses the full conversation and returns what we know so far
    3. is_ready() checks if we have the minimum fields to run analysis
    4. next_question() returns the single most important question to ask next
    5. Once is_ready() returns True, orchestrator triggers the full pipeline

Design principles:
    - One question at a time. Never multiple questions in one message.
    - Confirm what was understood before moving on.
    - Never ask for something the user already mentioned.
    - Works in both Hindi and English — responds in same language as user.
    - Pre-calculates nothing — just extracts and validates.
    - LLM never does math — only extracts text values into typed fields.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.base_agent import BaseAgent
from dataclasses import dataclass, field
from typing import Optional


# ─── Minimum fields required before analysis can run ─────────────────────────
REQUIRED_FIELDS = [
    "property_price",
    "area_sqft",
    "property_type",
    "monthly_income",
    "total_savings",
    "down_payment_available",
    "age",
]

# ─── Nice-to-have fields (improve analysis depth but not blocking) ─────────────
OPTIONAL_FIELDS = [
    "locality",
    "floor_number",
    "facing",
    "parking_included",
    "parking_cost",
    "monthly_expenses",
    "tenure_years",
    "annual_interest_rate",
    "existing_loan_emi",
    "builder_name",
    "project_name",
    "rera_number",
    "first_time_buyer",
    "owner_gender",
]

# ─── Question sequence — asked in this order if not yet collected ─────────────
# Each entry: (field_name, question_text)
QUESTION_SEQUENCE = [
    (
        "property_price",
        "What's the price the builder or seller has quoted? "
        "Even a rough number works — we'll refine it."
    ),
    (
        "locality",
        "Which area in Mumbai is this property in? "
        "(For example: Powai, Andheri West, Thane, Bandra, Borivali)"
    ),
    (
        "area_sqft",
        "What's the carpet area in square feet? "
        "Make sure it's carpet area, not super built-up — "
        "they differ by 20-35% in Mumbai and the difference matters a lot."
    ),
    (
        "property_type",
        "Is this an under-construction property or ready to move in?"
    ),
    (
        "floor_number",
        "Which floor is the flat on? "
        "(Floor number affects the price through floor rise charges)"
    ),
    (
        "facing",
        "Is it park-facing, sea-facing, road-facing, corner flat, or internal? "
        "This affects the PLC (Preferential Location Charges)."
    ),
    (
        "parking_included",
        "Is a parking spot included in the quoted price, or is it extra? "
        "In Mumbai parking can add ₹3L to ₹10L."
    ),
    (
        "monthly_income",
        "Now let's look at your finances. "
        "What's your monthly take-home income after tax?"
    ),
    (
        "monthly_expenses",
        "What are your total monthly expenses right now — "
        "rent, groceries, subscriptions, everything including any existing EMIs?"
    ),
    (
        "total_savings",
        "How much do you have saved up in total right now? "
        "Include FDs, savings account, liquid mutual funds — "
        "anything you can access within a month."
    ),
    (
        "down_payment_available",
        "Of your total savings, how much are you comfortable putting "
        "as down payment? "
        "Be honest — keeping some buffer after down payment is critical."
    ),
    (
        "age",
        "How old are you? This affects the maximum loan tenure calculation."
    ),
    (
        "first_time_buyer",
        "Is this your first property purchase?"
    ),
    (
        "builder_name",
        "What's the builder or developer's name? "
        "And do you have the project name or RERA number handy? "
        "We'll verify it on MahaRERA."
    ),
    (
        "owner_gender",
        "Will the property be registered in your name, "
        "your spouse's name, or jointly? "
        "(Female owner gets 1% stamp duty concession in Maharashtra — "
        "can save ₹50K-₹2L depending on property price)"
    ),
]


# ─── Collected data container ─────────────────────────────────────────────────

@dataclass
class CollectedData:
    # Property
    property_price:         Optional[float] = None
    locality:               Optional[str]   = None
    area_sqft:              Optional[float] = None
    floor_number:           Optional[int]   = None
    facing:                 Optional[str]   = None
    property_type:          Optional[str]   = None   # under_construction|ready_to_move
    parking_included:       Optional[bool]  = None
    parking_cost:           Optional[float] = None

    # Builder / legal
    builder_name:           Optional[str]   = None
    project_name:           Optional[str]   = None
    rera_number:            Optional[str]   = None

    # Financial
    monthly_income:         Optional[float] = None
    monthly_expenses:       Optional[float] = None
    total_savings:          Optional[float] = None
    down_payment_available: Optional[float] = None
    tenure_years:           Optional[int]   = None
    annual_interest_rate:   Optional[float] = None  # as decimal e.g. 0.085
    existing_loan_emi:      Optional[float] = None

    # Personal
    age:                    Optional[int]   = None
    first_time_buyer:       Optional[bool]  = None
    owner_gender:           Optional[str]   = None  # male|female|joint

    def missing_required(self) -> list:
        """Returns list of required field names that are still None."""
        return [f for f in REQUIRED_FIELDS if getattr(self, f) is None]

    def is_ready(self) -> bool:
        """True when all required fields are collected."""
        return len(self.missing_required()) == 0

    def next_question_field(self) -> Optional[str]:
        """
        Returns the field name of the next question to ask.
        Priority: required fields first (in QUESTION_SEQUENCE order),
        then optional fields.
        """
        for field_name, _ in QUESTION_SEQUENCE:
            if getattr(self, field_name) is None:
                return field_name
        return None

    def to_dict(self) -> dict:
        """Convert to plain dict, excluding None values."""
        return {
            k: v for k, v in self.__dict__.items()
            if v is not None
        }

    def completion_pct(self) -> int:
        """How complete is the data collection, 0-100."""
        total   = len(REQUIRED_FIELDS) + len(OPTIONAL_FIELDS)
        filled  = sum(
            1 for f in REQUIRED_FIELDS + OPTIONAL_FIELDS
            if getattr(self, f, None) is not None
        )
        return int((filled / total) * 100)


# ─── System prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are a warm, knowledgeable Mumbai real estate advisor helping someone
understand exactly what they're getting into before buying a home.

You are NOT a salesperson. You are on the buyer's side.
Your job is to collect enough information to run a complete financial
and legal risk analysis — then give them an honest verdict.

Mumbai knowledge you apply naturally in conversation:
- Carpet area vs super built-up: Mumbai builders quote super built-up
  which is 25-40% larger than the actual usable carpet area.
  Always ask for carpet area specifically.
- Floor rise charges: builders charge extra per floor above ground,
  typically ₹50-150 per sqft per floor.
- PLC: park-facing, sea-facing, corner units carry 2-8% premium.
- Parking: often ₹3L-10L extra in Mumbai, not included in base price.
- GST: 5% on under-construction, 0% on ready-to-move.
- Stamp duty: 5% for male, 4% for female owner + 1% metro cess always.
- Registration: capped at ₹30,000 in Maharashtra.
- RERA: all projects must be registered on MahaRERA. Always ask.
- Redevelopment risk: many Mumbai buildings are under redevelopment.
- Rental yield: only 2-3% in Mumbai — it's a long-term asset decision.

Conversation rules:
- Ask ONE question at a time. Never two questions in one message.
- Confirm what you understood before asking the next thing.
- If the user mentions a number, repeat it back to confirm.
- If the user says something vague ("decent area", "affordable"),
  ask them to be specific.
- If the user seems anxious or pressured (mentions "last unit",
  "price going up tomorrow"), acknowledge it calmly and remind them
  that a ₹1 crore decision deserves careful analysis.
- Respond in the same language the user writes in.
  If they write in Hindi, respond in Hindi.
  If they mix Hindi and English, match their style.

When you have enough data, end your message with exactly:
[READY_FOR_ANALYSIS]

CRITICAL RULES:
1. You ALWAYS respond in valid JSON. Your ENTIRE response must be a
   single JSON object. Start with {{ and end with }}.
2. NEVER respond in plain text Hindi or English outside the JSON.
3. Your assistant_message INSIDE the JSON can be in Hindi or English.
4. The JSON structure is always the same regardless of language.
5. ALWAYS extract numbers from the user message into extracted_values.
"""


class IntakeAgent(BaseAgent):

    def __init__(self):
        super().__init__(
            name="IntakeAgent",
            persona="Mumbai real estate advisor who collects buyer data through conversation",
            system_prompt=SYSTEM_PROMPT
        )

    # -------------------------------------------------------------------------
    # Primary method — call on every user message
    # -------------------------------------------------------------------------

    async def process_message(
        self,
        user_message:        str,
        conversation_history: list,     # list of {role, content} dicts
        collected_data:      CollectedData
    ) -> dict:
        """
        Process a user message and return:
            - assistant_message: what to say back to the user
            - updated_data: CollectedData with any new fields extracted
            - ready: True if enough data collected to run analysis
            - next_field: which field we're trying to collect next

        This is the only method the orchestrator needs to call.
        """
        # Build context for the LLM
        context = {
            "conversation_history": conversation_history[-10:],  # last 10 turns
            "latest_user_message":  user_message,
            "already_collected":    collected_data.to_dict(),
            "still_missing_required": collected_data.missing_required(),
            "next_field_to_collect":  collected_data.next_question_field(),
            "completion_pct":         collected_data.completion_pct(),
        }

        prompt = self.build_prompt(
            context=context,
            task=self._build_task(collected_data)
        )

        raw = await self.call(prompt)

        # Extract newly mentioned values from this message
        updated_data = self._merge_extracted(
            collected_data,
            raw.get("extracted_values", {})
        )

        # Check if ready
        ready = updated_data.is_ready() or raw.get("ready_for_analysis", False)

        return {
            "assistant_message": raw.get("assistant_message", ""),
            "updated_data":      updated_data,
            "ready":             ready,
            "next_field":        updated_data.next_question_field(),
            "acknowledged":      raw.get("acknowledged", ""),
        }

    # -------------------------------------------------------------------------
    # Standalone extractor — call on full conversation to rebuild state
    # -------------------------------------------------------------------------

    async def extract_from_history(
        self,
        conversation_history: list
    ) -> CollectedData:
        """
        Re-extract all data from the full conversation history.
        Used to rebuild CollectedData after a reconnect or page refresh.
        """
        context = {
            "full_conversation": conversation_history,
            "task_description": (
                "Read the entire conversation and extract every financial "
                "and property value the user has mentioned."
            )
        }

        prompt = self.build_prompt(
            context=context,
            task=self._build_extraction_task()
        )

        raw = await self.call(prompt)
        data = CollectedData()
        return self._merge_extracted(data, raw.get("extracted_values", {}))

    # -------------------------------------------------------------------------
    # Prompt builders
    # -------------------------------------------------------------------------

    def _build_task(self, collected_data: CollectedData) -> str:
        next_field   = collected_data.next_question_field()
        next_question = ""
        for fname, fq in QUESTION_SEQUENCE:
            if fname == next_field:
                next_question = fq
                break

        return f"""
You are helping a Mumbai home buyer. Extract data and ask the next question.

EXTRACTION RULES (do this first, always):
- "2 cr" or "2 crore" = property_price: 20000000
- "1.2 cr" = property_price: 12000000
- "80 lakh" or "80L" = property_price: 8000000
- "chembur", "powai", "andheri" etc = locality (string)
- "ready to move" or "RTM" = property_type: "ready_to_move"
- "under construction" or "UC" = property_type: "under_construction"
- Any income like "1.5 lakh" = monthly_income: 150000
- Any savings like "20 lakh saved" = total_savings: 2000000
- Always extract even if mentioned casually

NEXT FIELD TO COLLECT: {next_field}
QUESTION TO ASK: {next_question}

RESPONSE RULES:
1. Write assistant_message in the SAME LANGUAGE the user used
   (Hindi if they wrote Hindi, English if English, mix if they mixed)
2. In assistant_message: briefly confirm what you understood, then ask
   the next question. One question only.
3. Do NOT repeat the same question you just asked
4. Do NOT say you have no information if they just gave you some

OUTPUT: A single JSON object. Nothing outside it. No markdown.
{{
    "assistant_message": "your reply in user's language here",
    "acknowledged": "one line confirming what was extracted",
    "extracted_values": {{
        "property_price": 20000000,
        "locality": "Chembur East"
    }},
    "ready_for_analysis": false
}}

CRITICAL: extracted_values MUST contain every value the user mentioned.
If user said "2 cr in chembur east" then extracted_values must have
property_price: 20000000 AND locality: "Chembur East".
Never return an empty extracted_values if the user gave any data.
"""

    def _build_extraction_task(self) -> str:
        return """
Read the entire conversation and extract every financial and property
value the user has mentioned across all their messages.

Return ONLY extracted_values — no message, no acknowledgment.

Respond in this exact JSON format:
{
    "extracted_values": {
        "property_price": 12000000,
        "area_sqft": 750,
        "locality": "Powai"
    }
}
"""

    # -------------------------------------------------------------------------
    # Data merger — applies extracted values to CollectedData
    # -------------------------------------------------------------------------

    def _merge_extracted(
        self,
        existing: CollectedData,
        extracted: dict
    ) -> CollectedData:
        """
        Merge newly extracted values into existing CollectedData.
        Only updates fields that are currently None — never overwrites
        a value the user already confirmed.
        Type conversion is handled here so the LLM never needs to
        worry about int vs float vs bool.
        """
        # Mapping: field_name -> (attribute_name, converter_function)
        field_converters = {
            "property_price":         ("property_price",         float),
            "area_sqft":              ("area_sqft",              float),
            "floor_number":           ("floor_number",           int),
            "facing":                 ("facing",                 str),
            "property_type":          ("property_type",          self._normalize_property_type),
            "parking_included":       ("parking_included",       self._to_bool),
            "parking_cost":           ("parking_cost",           float),
            "monthly_income":         ("monthly_income",         float),
            "monthly_expenses":       ("monthly_expenses",       float),
            "total_savings":          ("total_savings",          float),
            "down_payment_available": ("down_payment_available", float),
            "tenure_years":           ("tenure_years",           int),
            "annual_interest_rate":   ("annual_interest_rate",   self._normalize_interest_rate),
            "existing_loan_emi":      ("existing_loan_emi",      float),
            "age":                    ("age",                    int),
            "first_time_buyer":       ("first_time_buyer",       self._to_bool),
            "owner_gender":           ("owner_gender",           str),
            "locality":               ("locality",               str),
            "builder_name":           ("builder_name",           str),
            "project_name":           ("project_name",           str),
            "rera_number":            ("rera_number",            str),
        }

        import copy
        updated = copy.copy(existing)

        for key, (attr, converter) in field_converters.items():
            raw_value = extracted.get(key)
            if raw_value is None:
                continue
            # Only set if not already collected
            if getattr(updated, attr) is None:
                try:
                    setattr(updated, attr, converter(raw_value))
                except (ValueError, TypeError) as e:
                    print(f"[IntakeAgent] Could not convert {key}={raw_value}: {e}")

        return updated

    # ─── Type converters ──────────────────────────────────────────────────────

    def _to_bool(self, value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "yes", "1", "haan", "ha")
        return bool(value)

    def _normalize_property_type(self, value: str) -> str:
        v = value.lower().strip()
        if any(x in v for x in ["under", "uc", "construction", "new"]):
            return "under_construction"
        return "ready_to_move"

    def _normalize_interest_rate(self, value) -> float:
        """
        Handles both decimal (0.085) and percentage (8.5) formats.
        If user says 8.5 we convert to 0.085.
        If already decimal like 0.085 we keep it.
        """
        v = float(value)
        if v > 1:          # user gave percentage like 8.5
            return v / 100
        return v           # already decimal like 0.085