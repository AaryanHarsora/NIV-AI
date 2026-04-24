"""
WhatsApp webhook endpoints for NIV AI Concierge.

GET  /api/v1/whatsapp/webhook — webhook verification (Meta challenge-response)
POST /api/v1/whatsapp/webhook — incoming message handler

Controlled by WHATSAPP_ENABLED env var. Returns 200 OK for all POST requests
regardless of WHATSAPP_ENABLED to prevent Meta from disabling the webhook.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response

from backend.integrations.whatsapp_bot import VERIFY_TOKEN, handle_incoming_message

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")


@router.get("/whatsapp/webhook", include_in_schema=True)
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
) -> Response:
    """
    Meta webhook verification. Responds to hub.challenge when verify token matches.

    Args:
        hub_mode: Must be 'subscribe' for verification.
        hub_verify_token: Must match WHATSAPP_VERIFY_TOKEN env var.
        hub_challenge: Challenge string to echo back.

    Returns:
        Plain text hub_challenge on success, 403 on failure.
    """
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified successfully")
        return Response(content=hub_challenge or "", media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed — token mismatch")


@router.post("/whatsapp/webhook", include_in_schema=True)
async def receive_message(request: Request, background_tasks: BackgroundTasks):
    """
    Receives incoming WhatsApp messages from Meta webhook.
    Processes messages in background tasks to return 200 immediately.
    Meta requires sub-5-second webhook response time.

    Args:
        request: FastAPI request with Meta webhook payload.
        background_tasks: FastAPI background task runner.

    Returns:
        Always {"status": "ok"} — Meta retries on non-200 responses.
    """
    try:
        payload = await request.json()
        entry = payload.get("entry", [])
        for e in entry:
            for change in e.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                for msg in messages:
                    phone = msg.get("from", "")
                    msg_type = msg.get("type", "")
                    if msg_type == "text" and phone:
                        text = msg.get("text", {}).get("body", "")
                        if text:
                            background_tasks.add_task(handle_incoming_message, phone, text)
    except Exception as exc:
        logger.warning("WhatsApp webhook parse failed: %s", exc)
    return {"status": "ok"}
