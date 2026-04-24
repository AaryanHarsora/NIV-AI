"""
WhatsApp AI Concierge for NIV AI.

Handles incoming WhatsApp messages via Meta Business API webhook.
Conducts a conversational property analysis flow:
  1. Receives URL or property description
  2. Asks 4-5 financial questions
  3. Runs /api/v1/calculate for instant preview
  4. Runs full 6-agent pipeline on confirmation
  5. Replies with verdict + shareable URL

Session state is stored in Firestore 'whatsapp_sessions' collection.
Controlled by WHATSAPP_ENABLED env var (default: false).
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

WHATSAPP_ENABLED = os.getenv("WHATSAPP_ENABLED", "false").lower() == "true"
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "niv_ai_verify")
SEND_URL = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"

_SESSION_TTL_MINUTES = 30


@dataclass
class ConversationState:
    """Tracks multi-turn WhatsApp conversation state."""

    phone: str
    stage: str = "awaiting_property"
    # stage: "awaiting_property" | "awaiting_income" | "awaiting_savings"
    #        | "awaiting_emis" | "awaiting_dp" | "confirming" | "complete"
    property_price: Optional[float] = None
    location: Optional[str] = None
    config: str = "2BHK"
    income: Optional[float] = None
    savings: Optional[float] = None
    existing_emis: float = 0.0
    down_payment: Optional[float] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_message_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_amount(text: str) -> Optional[float]:
    """
    Parses a rupee amount from user text.
    Handles: 50000, 50k, 5L, 5 lakh, 50,000

    Args:
        text: User input string.

    Returns:
        Float amount in rupees, or None if not parseable.
    """
    text = text.strip().lower().replace(",", "")
    m_lakh = re.search(r"(\d+(?:\.\d+)?)\s*(?:l(?:akh)?|lacs?)", text)
    if m_lakh:
        return float(m_lakh.group(1)) * 100_000
    m_k = re.search(r"(\d+(?:\.\d+)?)\s*k", text)
    if m_k:
        return float(m_k.group(1)) * 1_000
    m_cr = re.search(r"(\d+(?:\.\d+)?)\s*(?:cr(?:ores?)?)", text)
    if m_cr:
        return float(m_cr.group(1)) * 10_000_000
    m_num = re.search(r"(\d+(?:\.\d+)?)", text)
    if m_num:
        val = float(m_num.group(1))
        # Ambiguous short numbers — assume lakh if < 1000 and > 0
        if val > 0 and val < 1000:
            return val * 100_000
        return val
    return None


async def send_whatsapp_message(to: str, text: str) -> bool:
    """
    Sends a WhatsApp text message via Meta Business API.
    Never raises — logs and returns False on failure.

    Args:
        to: Recipient phone number with country code (no +).
        text: Message text to send.

    Returns:
        True on success, False on failure.
    """
    if not WHATSAPP_ENABLED or not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        logger.debug("WhatsApp disabled or not configured — skipping send to %s", to)
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                SEND_URL,
                headers={
                    "Authorization": f"Bearer {ACCESS_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "text",
                    "text": {"body": text},
                },
            )
            if resp.status_code == 200:
                return True
            logger.warning("WhatsApp send failed (%s): %s", resp.status_code, resp.text[:200])
            return False
    except Exception as exc:
        logger.warning("WhatsApp send exception: %s", exc)
        return False


async def get_session(phone: str) -> Optional[ConversationState]:
    """
    Retrieves conversation state from Firestore.

    Args:
        phone: Phone number as session key.

    Returns:
        ConversationState or None if not found / expired.
    """
    try:
        from backend.firebase import firestore as fs
        db = fs._get_db()
        if db is None:
            return None
        doc = db.collection("whatsapp_sessions").document(phone).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        # Check TTL
        last = datetime.fromisoformat(data.get("last_message_at", _now_iso()))
        elapsed = (datetime.now(timezone.utc) - last.replace(tzinfo=timezone.utc)).total_seconds() / 60
        if elapsed > _SESSION_TTL_MINUTES:
            await clear_session(phone)
            return None
        return ConversationState(**{k: v for k, v in data.items() if k in ConversationState.__dataclass_fields__})
    except Exception as exc:
        logger.warning("WhatsApp session read failed: %s", exc)
        return None


async def save_session(state: ConversationState) -> None:
    """
    Persists conversation state to Firestore.

    Args:
        state: ConversationState to persist.
    """
    try:
        from backend.firebase import firestore as fs
        db = fs._get_db()
        if db is None:
            return
        state.last_message_at = _now_iso()
        db.collection("whatsapp_sessions").document(state.phone).set(state.__dict__)
    except Exception as exc:
        logger.warning("WhatsApp session save failed: %s", exc)


async def clear_session(phone: str) -> None:
    """
    Removes completed/expired session from Firestore.

    Args:
        phone: Phone number as session key.
    """
    try:
        from backend.firebase import firestore as fs
        db = fs._get_db()
        if db is None:
            return
        db.collection("whatsapp_sessions").document(phone).delete()
    except Exception as exc:
        logger.warning("WhatsApp session clear failed: %s", exc)


def extract_property_details_from_url(url: str) -> dict:
    """
    Attempts to scrape basic property details from MagicBricks/99acres URL.
    Uses httpx + BeautifulSoup. Returns partial dict, never raises.

    Args:
        url: Property listing URL.

    Returns:
        Dict with keys: price (float|None), location (str|None), config (str|None)
    """
    result: dict = {"price": None, "location": None, "config": None}
    try:
        import httpx as _httpx
        from bs4 import BeautifulSoup

        with _httpx.Client(timeout=8.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return result
            soup = BeautifulSoup(resp.text, "html.parser")

            # MagicBricks price
            for sel in ["[data-testid='price']", ".mb-srp-card__price", ".price"]:
                el = soup.select_one(sel)
                if el:
                    price_text = el.get_text()
                    result["price"] = _parse_amount(price_text)
                    break

            # Location
            for sel in [".mb-srp-card__summary--value", ".loc_sector_below_breadcrumb", "h1"]:
                el = soup.select_one(sel)
                if el:
                    result["location"] = el.get_text(strip=True)[:100]
                    break

            # Config from title
            title = soup.title.string if soup.title else ""
            for cfg in ["5BHK", "4BHK", "3BHK", "2BHK", "1BHK"]:
                if cfg in title.upper():
                    result["config"] = cfg
                    break
    except Exception as exc:
        logger.debug("URL scrape failed for %s: %s", url, exc)
    return result


def format_verdict_message(report: dict, share_url: str) -> str:
    """
    Formats the final analysis result as a WhatsApp-friendly message.

    Args:
        report: Full pipeline report dict.
        share_url: Shareable report URL.

    Returns:
        Formatted WhatsApp message string (max ~1000 chars).
    """
    verdict = (report.get("verdict") or "risky").upper()
    confidence = report.get("confidence_score", "?")
    icons = {"SAFE": "✅", "RISKY": "⚠️", "RECONSIDER": "🚫"}
    icon = icons.get(verdict, "⚠️")

    c = report.get("computed_numbers", {})
    emi = c.get("monthly_emi", 0)
    emi_ratio = round(c.get("emi_to_income_ratio", 0) * 100, 1)
    runway = round(c.get("emergency_runway_months", 0), 1)
    stress = len([s for s in report.get("stress_scenarios", []) if s.get("can_survive")])

    top_risk = ""
    flags = report.get("property_assessment", {}).get("property_flags", [])
    high_flags = [f for f in flags if f.get("severity") == "high"]
    if high_flags:
        top_risk = f"\n⚠️ Top Risk:\n{high_flags[0].get('flag', '')} — {high_flags[0].get('detail', '')[:80]}"

    msg = (
        f"🏠 *NIV AI Analysis Complete*\n\n"
        f"Verdict: {icon} *{verdict}* (Confidence: {confidence}/10)\n\n"
        f"📊 Key Numbers:\n"
        f"• EMI: ₹{emi:,.0f}/month ({emi_ratio}% of income)\n"
        f"• Emergency Runway: {runway} months {'✓' if runway >= 6 else '✗'}\n"
        f"• Stress Tests: {stress}/4 passed {'✓' if stress >= 3 else '✗'}"
        f"{top_risk}\n\n"
        f"📎 Full Analysis: {share_url}\n\n"
        f"_Powered by NIV AI — Not financial advice_"
    )
    return msg[:1200]


async def handle_incoming_message(phone: str, message_text: str) -> None:
    """
    Main conversation handler. Manages multi-turn state machine for property analysis.

    Args:
        phone: Sender's phone number.
        message_text: Incoming message text.
    """
    text = message_text.strip()
    lower = text.lower()

    # Reset commands
    if any(cmd in lower for cmd in ["reset", "start", "cancel", "new"]):
        await clear_session(phone)
        await send_whatsapp_message(
            phone,
            "👋 Welcome to *NIV AI* — Your Home Buying Advisor!\n\n"
            "Send me a property listing URL (MagicBricks/99acres) or type the property details:\n"
            "Example: _₹85L 2BHK in Andheri West_",
        )
        return

    state = await get_session(phone)

    # New session
    if state is None:
        state = ConversationState(phone=phone)
        # Check if URL was sent
        url_match = re.search(r"https?://\S+", text)
        if url_match:
            details = extract_property_details_from_url(url_match.group(0))
            if details.get("price"):
                state.property_price = details["price"]
            if details.get("location"):
                state.location = details["location"]
            if details.get("config"):
                state.config = details["config"]
        else:
            # Try to parse price and location from text
            price = _parse_amount(text)
            if price:
                state.property_price = price
            loc_match = re.search(r"in\s+([A-Za-z\s]+?)(?:\s*$|\.|,)", text, re.IGNORECASE)
            if loc_match:
                state.location = loc_match.group(1).strip()
            for cfg in ["5BHK", "4BHK", "3BHK", "2BHK", "1BHK"]:
                if cfg.lower() in lower:
                    state.config = cfg
                    break

        if state.property_price and state.location:
            state.stage = "awaiting_income"
            await save_session(state)
            await send_whatsapp_message(
                phone,
                f"Got it! Analyzing a *{state.config}* at *{state.location}* "
                f"(₹{state.property_price:,.0f}) 🏡\n\n"
                f"*Step 1/4:* What is your monthly take-home income? "
                f"(Include spouse if applicable)\n_Example: 1.2L or 120000_",
            )
        else:
            await save_session(state)
            await send_whatsapp_message(
                phone,
                "👋 Welcome to *NIV AI*!\n\n"
                "Please share the property details. Send a listing URL or type:\n"
                "_Price, Configuration, Location_\n\n"
                "Example: _₹85L 2BHK Andheri West_ or paste a MagicBricks link",
            )
        return

    # Stage-based handling
    if state.stage == "awaiting_property":
        price = _parse_amount(text)
        if price:
            state.property_price = price
        loc_match = re.search(r"(?:in\s+)?([A-Za-z\s]+)", text, re.IGNORECASE)
        if loc_match and not state.location:
            state.location = loc_match.group(1).strip()[:50]
        for cfg in ["5BHK", "4BHK", "3BHK", "2BHK", "1BHK"]:
            if cfg.lower() in lower:
                state.config = cfg
                break

        if state.property_price and state.location:
            state.stage = "awaiting_income"
            await save_session(state)
            await send_whatsapp_message(
                phone,
                f"*{state.config}* at *{state.location}* (₹{state.property_price:,.0f}) noted ✓\n\n"
                f"*Step 1/4:* What is your monthly household income?\n_Type a number like 120000 or 1.2L_",
            )
        else:
            await send_whatsapp_message(
                phone,
                "I need the property price and location. Please share:\n"
                "_Price, Config, Location — e.g. ₹85L 2BHK Andheri West_",
            )
        return

    elif state.stage == "awaiting_income":
        income = _parse_amount(text)
        if not income:
            await send_whatsapp_message(phone, "Please enter a valid monthly income (e.g. 1.2L or 120000)")
            return
        state.income = income
        state.stage = "awaiting_savings"
        await save_session(state)
        await send_whatsapp_message(
            phone,
            f"Income: ₹{income:,.0f}/month noted ✓\n\n"
            f"*Step 2/4:* What are your total liquid savings? (bank balance + FDs + stocks)\n"
            f"_Type 0 if unsure_",
        )

    elif state.stage == "awaiting_savings":
        savings = _parse_amount(text)
        if savings is None:
            await send_whatsapp_message(phone, "Please enter your liquid savings amount (type 0 if none)")
            return
        state.savings = savings
        state.stage = "awaiting_emis"
        await save_session(state)
        await send_whatsapp_message(
            phone,
            f"Savings: ₹{savings:,.0f} noted ✓\n\n"
            f"*Step 3/4:* Any existing loan EMIs (car loan, personal loan, etc.)?\n"
            f"_Type 0 if none_",
        )

    elif state.stage == "awaiting_emis":
        emis = _parse_amount(text) or 0.0
        state.existing_emis = emis
        state.stage = "awaiting_dp"
        await save_session(state)
        await send_whatsapp_message(
            phone,
            f"Existing EMIs: ₹{emis:,.0f}/month noted ✓\n\n"
            f"*Step 4/4:* How much can you pay as down payment? "
            f"(Minimum 20% = ₹{state.property_price * 0.20:,.0f})\n"
            f"_Type the amount you have arranged_",
        )

    elif state.stage == "awaiting_dp":
        dp = _parse_amount(text)
        if not dp or dp <= 0:
            await send_whatsapp_message(phone, "Please enter a valid down payment amount")
            return
        state.down_payment = dp
        state.stage = "confirming"
        await save_session(state)

        # Run quick calculate preview
        try:
            prop_price = state.property_price or 0
            income = state.income or 0
            from backend.calculations.financial import compute_all
            nums = compute_all(
                monthly_income=income,
                spouse_income=0,
                employment_type="salaried",
                years_in_job=2.0,
                expected_growth_pct=8.0,
                existing_emis=state.existing_emis,
                monthly_expenses=income * 0.40,
                current_rent=0,
                liquid_savings=state.savings or 0,
                other_investments=0,
                dependents=0,
                property_price=prop_price,
                location_area=state.location or "Mumbai",
                configuration=state.config,
                carpet_area_sqft=650,
                is_ready_to_move=True,
                buyer_gender="male",
                down_payment=dp,
                loan_tenure_years=20,
                interest_rate=8.5,
                is_first_property=True,
            )
            emi = nums.monthly_emi
            emi_ratio = round(nums.emi_to_income_ratio * 100, 1)
            runway = round(nums.emergency_runway_months, 1)
            preview = (
                f"📊 *Quick Preview:*\n"
                f"• EMI: ₹{emi:,.0f}/month\n"
                f"• EMI/Income: {emi_ratio}% {'✓' if emi_ratio < 45 else '⚠️'}\n"
                f"• Emergency Runway: {runway} months {'✓' if runway > 3 else '⚠️'}\n\n"
                f"Want a *full AI analysis* with 6 expert agents? Reply *Yes* or *No*"
            )
        except Exception as exc:
            logger.warning("WhatsApp quick calc failed: %s", exc)
            preview = (
                f"Got all your details ✓\n\n"
                f"Want a *full AI analysis* with 6 expert agents? Reply *Yes* or *No*"
            )

        await send_whatsapp_message(phone, preview)

    elif state.stage == "confirming":
        if lower in ("yes", "y", "haan", "ha", "ok", "okay", "sure"):
            state.stage = "complete"
            await save_session(state)
            await send_whatsapp_message(
                phone,
                "⏳ Running full analysis... This takes about 30-45 seconds. I'll send the results shortly.",
            )

            try:
                from backend.agents import pipeline
                raw_input = {
                    "financial": {
                        "monthly_income": state.income or 0,
                        "spouse_income": 0,
                        "employment_type": "salaried",
                        "years_in_current_job": 2,
                        "expected_annual_growth_pct": 8,
                        "existing_emis": state.existing_emis,
                        "monthly_expenses": (state.income or 0) * 0.40,
                        "current_rent": 0,
                        "liquid_savings": state.savings or 0,
                        "other_investments": 0,
                        "dependents": 0,
                    },
                    "property": {
                        "property_price": state.property_price or 0,
                        "location_area": state.location or "Mumbai",
                        "location_city": "Mumbai",
                        "configuration": state.config,
                        "carpet_area_sqft": 650,
                        "is_ready_to_move": True,
                        "is_rera_registered": None,
                        "builder_name": "",
                        "possession_date": "",
                        "down_payment_available": state.down_payment or 0,
                        "loan_tenure_years": 20,
                        "expected_interest_rate": 8.5,
                        "buyer_gender": "male",
                        "commute_distance_km": 0,
                        "is_first_property": True,
                        "property_notes": "",
                    },
                    "output_language": "english",
                }
                report = await pipeline.run_analysis(raw_input)

                # Save to Firestore and get share URL
                from backend.firebase import firestore as fs
                report_id = await fs.save_report(report, raw_input, "whatsapp_bot")
                share_url = f"https://niv.ai/report/{report_id}" if report_id else "niv.ai"

                verdict_msg = format_verdict_message(report, share_url)
                await send_whatsapp_message(phone, verdict_msg)

            except Exception as exc:
                logger.error("WhatsApp pipeline failed: %s", exc)
                await send_whatsapp_message(
                    phone,
                    "Sorry, the analysis encountered an error. "
                    "Please try again or visit our website for a full analysis.",
                )

            await clear_session(phone)

        elif lower in ("no", "n", "nahi", "nope"):
            await clear_session(phone)
            await send_whatsapp_message(
                phone,
                "No problem! Come back anytime to analyze a property.\n"
                "Type *start* whenever you're ready 🏠",
            )
        else:
            await send_whatsapp_message(phone, "Please reply *Yes* to run the full analysis or *No* to cancel.")
