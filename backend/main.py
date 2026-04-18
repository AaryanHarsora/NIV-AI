"""
main.py — FastAPI application for NIV AI.

Deliberately thin:
    - Receives requests, validates auth, calls orchestrator, returns responses.
    - No business logic. No financial math. No AI calls inside routes.

Route groups:
    /health                     — health check
    /chat/*                     — new chat-first flow (primary)
    /session/*                  — session management
    /analyze/*                  — legacy analysis pipeline (kept for compatibility)
    /conversation/*             — follow-up turns
    /roundtable/*               — WebSocket live discussion
    /report/*                   — PDF download
"""

import os
import json
import asyncio
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

from fastapi import (
    FastAPI, Depends, HTTPException,
    WebSocket, WebSocketDisconnect,
    Query, UploadFile, File
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

# ─── Firebase ────────────────────────────────────────────────────────────────
from firebase.firebase_admin import initialize_firebase
from firebase_admin import auth as firebase_auth
from auth.middleware import verify_token
from firebase.firestore_ops import (
    create_session,
    get_session,
    get_session_history,
    save_behavioral_intake,
    get_behavioral_intake,
    save_financial_inputs,
    save_simulation_results,
)

# ─── Schemas ─────────────────────────────────────────────────────────────────
from schemas.schemas import (
    # Existing
    UserInput,
    BehavioralIntake,
    ConversationMessage,
    APIResponse,
    AnalysisResponse,
    SessionStartResponse,
    ConversationResponse,
    VerdictOutput,
    PropertyType,
    BehavioralAnswer,
    # New chat schemas
    ChatMessageRequest,
    ChatMessageResponse,
    ChatStartResponse,
    ChatStatus,
    ChatRole,
    ChatMessage,
    ReportDownloadResponse,
)

# ─── Deterministic engines ────────────────────────────────────────────────────
from engines.mumbai_costs import calculate_mumbai_true_cost
from agents.deterministic.financial_reality import calculate_affordability
from agents.deterministic.scenario_simulation import run_all_scenarios
from agents.deterministic.risk_scorer import calculate_risk_score

# ─── Chat agents ─────────────────────────────────────────────────────────────
from agents.chat.intake_agent import IntakeAgent, CollectedData
from agents.chat.question_engine import QuestionEngine

# ─── PDF ─────────────────────────────────────────────────────────────────────
from engines.pdf_generator import generate_pdf


# ─── App init ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="NIV AI — Mumbai Home Buying Advisor",
    description="Risk-aware home buying decision intelligence for Mumbai families",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Singletons ──────────────────────────────────────────────────────────────
orchestrator    = None
intake_agent    = None
question_engine = None

# In-memory chat sessions: session_id -> CollectedData
# Same limitation as blackboards — single instance only
# Fine for hackathon, fix with Firestore serialization for production
_chat_sessions: dict[str, dict] = {}


@app.on_event("startup")
async def startup_event():
    global orchestrator, intake_agent, question_engine

    try:
        initialize_firebase()
        print("[Startup] Firebase initialized")
    except Exception as e:
        print(f"[Startup] Firebase init failed (non-critical in dev): {e}")

    try:
        from agents.orchestration.orchestrator import Orchestrator
        orchestrator = Orchestrator()
        print("[Startup] Orchestrator initialized")
    except Exception as e:
        print(f"[Startup] Orchestrator init failed: {e}")

    try:
        intake_agent    = IntakeAgent()
        question_engine = QuestionEngine()
        print("[Startup] Chat agents initialized")
    except Exception as e:
        print(f"[Startup] Chat agents init failed: {e}")


# =============================================================================
# HEALTH
# =============================================================================

@app.get("/health")
async def health_check():
    return {
        "status":  "healthy",
        "service": "niv-ai-mumbai-advisor",
        "version": "2.0.0",
        "groq":    bool(os.getenv("GROQ_API_KEY")),
        "chat_ready": intake_agent is not None,
    }


# =============================================================================
# CHAT — primary flow
# =============================================================================

@app.post("/chat/start", response_model=APIResponse)
async def chat_start():
    """
    Creates a new chat session.
    No auth required for hackathon demo — add verify_token dep for production.
    Returns session_id and the opening message.
    """
    import uuid
    session_id = str(uuid.uuid4())
    now        = datetime.now(timezone.utc).isoformat()

    _chat_sessions[session_id] = {
        "collected":   CollectedData(),
        "history":     [],
        "status":      ChatStatus.COLLECTING,
        "created_at":  now,
    }

    opening = question_engine.get_opening_message() if question_engine else (
        "Hi! Tell me about the property you're looking at in Mumbai."
    )

    # Add opening message to history
    _chat_sessions[session_id]["history"].append({
        "role":      ChatRole.ASSISTANT,
        "content":   opening,
        "timestamp": now,
    })

    return APIResponse(
        success=True,
        message="Chat session created",
        data=ChatStartResponse(
            session_id=session_id,
            opening_message=opening,
            created_at=now,
        ).model_dump()
    )


@app.post("/chat/message", response_model=APIResponse)
async def chat_message(req: ChatMessageRequest):
    """
    Process a user message in an existing chat session.

    Flow:
        1. Load session state
        2. QuestionEngine pre-processes (skip detection, attempt tracking)
        3. IntakeAgent extracts data and generates response
        4. If ready → trigger full analysis pipeline async
        5. Return response + progress
    """
    session_id = req.session_id

    if session_id not in _chat_sessions:
        raise HTTPException(status_code=404, detail="Chat session not found. Call /chat/start first.")

    session   = _chat_sessions[session_id]
    collected = session["collected"]
    history   = session["history"]
    now       = datetime.now(timezone.utc).isoformat()

    # Add user message to history
    history.append({
        "role":      ChatRole.USER,
        "content":   req.message,
        "timestamp": now,
    })

    # ── QuestionEngine pre-process ────────────────────────────────────────────
    pre = question_engine.pre_process(session_id, req.message, collected)
    collected = pre["updated_collected"]

    if pre["should_skip_llm"]:
        # Deterministic response — no LLM needed
        assistant_msg = pre["override_message"]
        session["collected"] = collected

        history.append({
            "role":      ChatRole.ASSISTANT,
            "content":   assistant_msg,
            "timestamp": now,
        })

        progress = question_engine.get_progress(session_id, collected)
        return APIResponse(
            success=True,
            message="ok",
            data=ChatMessageResponse(
                session_id=session_id,
                assistant_message=assistant_msg,
                status=ChatStatus.COLLECTING,
                progress_pct=progress["completion_pct"],
                required_remaining=progress["required_remaining"],
                ready=False,
            ).model_dump()
        )

    # ── IntakeAgent processes message ─────────────────────────────────────────
    if not intake_agent:
        raise HTTPException(status_code=503, detail="Chat agent not ready")

    try:
        result = await intake_agent.process_message(
            user_message=req.message,
            conversation_history=history[:-1],
            collected_data=collected
        )
    except Exception as e:
        print(f"[IntakeAgent] LLM error: {e}")
        result = {
            "assistant_message": question_engine._get_question_text(
                collected.next_question_field()
            ) or "Could you tell me more about the property?",
            "updated_collected": collected,
            "ready": False,
            "acknowledged": "",
        }

    collected     = result.get("updated_collected", collected)
    assistant_msg = result.get("assistant_message", "")
    session["collected"] = collected

    if not assistant_msg:
        assistant_msg = question_engine._get_question_text(
            collected.next_question_field()
        ) or "Could you tell me more?"

    # Strip [READY_FOR_ANALYSIS] tag from the displayed message
    display_msg = assistant_msg.replace("[READY_FOR_ANALYSIS]", "").strip()

    history.append({
        "role":      ChatRole.ASSISTANT,
        "content":   display_msg,
        "timestamp": now,
    })

    progress = question_engine.get_progress(session_id, collected)
    ready    = result["ready"]

    # ── Trigger analysis if ready ─────────────────────────────────────────────
    if ready:
        session["status"] = ChatStatus.ANALYZING

        # Apply defaults to any missing optional fields
        final_collected = question_engine.apply_analysis_defaults(collected)
        session["collected"] = final_collected

        # Fire analysis pipeline in background
        # Frontend will poll /chat/status/{session_id} or connect to
        # /chat/roundtable/{session_id} WebSocket for live updates
        asyncio.create_task(
            _run_analysis_pipeline(session_id, final_collected)
        )

        analysis_msg = question_engine.get_analysis_message(final_collected)
        history.append({
            "role":      ChatRole.ASSISTANT,
            "content":   analysis_msg,
            "timestamp": now,
        })

        return APIResponse(
            success=True,
            message="ok",
            data=ChatMessageResponse(
                session_id=session_id,
                assistant_message=display_msg + "\n\n" + analysis_msg,
                status=ChatStatus.ANALYZING,
                progress_pct=100,
                required_remaining=0,
                ready=True,
            ).model_dump()
        )

    return APIResponse(
        success=True,
        message="ok",
        data=ChatMessageResponse(
            session_id=session_id,
            assistant_message=display_msg,
            status=ChatStatus.COLLECTING,
            progress_pct=progress["completion_pct"],
            required_remaining=progress["required_remaining"],
            ready=False,
        ).model_dump()
    )


@app.get("/chat/status/{session_id}", response_model=APIResponse)
async def chat_status(session_id: str):
    """
    Returns current status of a chat session.
    Frontend polls this after analysis is triggered to know when report is ready.
    """
    if session_id not in _chat_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session  = _chat_sessions[session_id]
    collected = session["collected"]
    progress  = question_engine.get_progress(session_id, collected)

    return APIResponse(
        success=True,
        message="ok",
        data={
            "session_id":         session_id,
            "status":             session["status"],
            "progress_pct":       progress["completion_pct"],
            "required_remaining": progress["required_remaining"],
            "report_url":         session.get("report_url"),
            "error":              session.get("error"),
        }
    )


@app.get("/chat/history/{session_id}", response_model=APIResponse)
async def chat_history(session_id: str):
    """Returns the full conversation history for a session."""
    if session_id not in _chat_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = _chat_sessions[session_id]
    return APIResponse(
        success=True,
        message="ok",
        data={
            "session_id": session_id,
            "messages":   session["history"],
            "status":     session["status"],
        }
    )


# =============================================================================
# CHAT WebSocket — live roundtable streaming
# =============================================================================

@app.websocket("/chat/roundtable/{session_id}")
async def chat_roundtable_ws(websocket: WebSocket, session_id: str):
    """
    WebSocket for the live roundtable discussion.
    Frontend connects after /chat/message returns ready=True.
    Streams Marcus, Zara, Soren messages in real time.
    No auth for hackathon — add token query param for production.
    """
    if session_id not in _chat_sessions:
        await websocket.close(code=4004, reason="Session not found")
        return

    session = _chat_sessions[session_id]

    await websocket.accept()

    # Wait for analysis to complete before starting roundtable
    # Poll with timeout — max 120 seconds
    wait_seconds = 0
    while session["status"] == ChatStatus.ANALYZING and wait_seconds < 120:
        await asyncio.sleep(2)
        wait_seconds += 2

    if session["status"] == ChatStatus.ERROR:
        await websocket.send_text(json.dumps({
            "type":      "error",
            "message":   session.get("error", "Analysis failed"),
            "recoverable": False,
        }))
        await websocket.close()
        return

    if not orchestrator:
        await websocket.send_text(json.dumps({
            "type":    "error",
            "message": "Roundtable engine not available",
            "recoverable": False,
        }))
        await websocket.close()
        return

    session["status"] = ChatStatus.ROUNDTABLE

    try:
        await orchestrator.run_roundtable(
            session_id=session_id,
            websocket=websocket,
        )
        session["status"] = ChatStatus.COMPLETE
    except WebSocketDisconnect:
        print(f"[WS] Client disconnected: {session_id}")
    except Exception as e:
        try:
            await websocket.send_text(json.dumps({
                "type":    "error",
                "message": str(e),
                "recoverable": False,
            }))
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# =============================================================================
# REPORT — PDF download
# =============================================================================

@app.get("/report/{session_id}")
async def get_report(session_id: str):
    """
    Generates and returns the PDF report as a direct download.
    No GCS — bytes returned directly in response.
    Frontend: window.open('/report/{session_id}') to trigger download.
    """
    if session_id not in _chat_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = _chat_sessions[session_id]

    if session["status"] not in (ChatStatus.COMPLETE, ChatStatus.ROUNDTABLE):
        raise HTTPException(
            status_code=400,
            detail="Analysis not complete yet. Wait for roundtable to finish."
        )

    # Get presentation and verdict from orchestrator blackboard
    if not orchestrator or session_id not in orchestrator._blackboards:
        raise HTTPException(
            status_code=400,
            detail="Analysis data not found. Run full analysis first."
        )

    bb_state = orchestrator._blackboards[session_id].state

    if not bb_state.verdict or not bb_state.presentation:
        raise HTTPException(
            status_code=400,
            detail="Verdict not ready. Complete the roundtable first."
        )

    try:
        pdf_bytes = generate_pdf(
            session_id=session_id,
            presentation_output=bb_state.presentation,
            verdict_output=bb_state.verdict,
            mumbai_costs=session.get("mumbai_costs"),
            collected_data=session["collected"],
        )

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="NIV_Report_{session_id[:8]}.pdf"',
                "Content-Length": str(len(pdf_bytes)),
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")


# =============================================================================
# LEGACY ROUTES — kept for backward compatibility
# =============================================================================

@app.post("/session/start", response_model=APIResponse)
async def start_session(uid: str = Depends(verify_token)):
    session_id = create_session(user_id=uid, title="New Analysis", city="Mumbai", state="maharashtra")
    now = datetime.now(timezone.utc).isoformat()
    return APIResponse(
        success=True,
        message="Session created",
        data=SessionStartResponse(session_id=session_id, user_id=uid, created_at=now).model_dump()
    )


@app.get("/session/{session_id}", response_model=APIResponse)
async def get_session_route(session_id: str, uid: str = Depends(verify_token)):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.get("user_id") != uid:
        raise HTTPException(status_code=403, detail="Access denied")
    return APIResponse(success=True, message="ok", data=session)


@app.get("/session/history/{user_id}", response_model=APIResponse)
async def get_history_route(user_id: str, uid: str = Depends(verify_token)):
    if user_id != uid:
        raise HTTPException(status_code=403, detail="Access denied")
    return APIResponse(success=True, message="ok", data=get_session_history(user_id))


@app.websocket("/roundtable/{session_id}")
async def roundtable_ws(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(""),
):
    try:
        decoded  = firebase_auth.verify_id_token(token)
        user_uid = decoded["uid"]
    except Exception:
        await websocket.close(code=4001, reason="Invalid token")
        return

    session = get_session(session_id)
    if not session or session.get("user_id") != user_uid:
        await websocket.close(code=4003, reason="Access denied")
        return

    await websocket.accept()

    if not orchestrator:
        await websocket.send_text(json.dumps({"type": "error", "message": "Not available", "recoverable": False}))
        await websocket.close()
        return

    try:
        await orchestrator.run_roundtable(session_id=session_id, websocket=websocket)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(e), "recoverable": False}))
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# =============================================================================
# INTERNAL — analysis pipeline (called via asyncio.create_task)
# =============================================================================

async def _run_analysis_pipeline(session_id: str, collected: CollectedData):
    """
    Runs the full analysis pipeline after intake is complete.
    Called as a background task — never blocks the HTTP response.

    Steps:
        1. Build UserInput from CollectedData
        2. Run mumbai_costs (deterministic)
        3. Run financial_reality, scenarios, risk_score (deterministic)
        4. Build behavioral answers from conversation (heuristic)
        5. Call orchestrator.analyze() (AI agents)
        6. Store results for roundtable and report
    """
    session = _chat_sessions.get(session_id)
    if not session:
        return

    try:
        # ── Step 1: Build UserInput ───────────────────────────────────────────
        loan_amount = max(
            collected.property_price - collected.down_payment_available, 0
        )

        user_input = UserInput(
            monthly_income       = collected.monthly_income,
            monthly_expenses     = collected.monthly_expenses or collected.monthly_income * 0.4,
            total_savings        = collected.total_savings,
            down_payment         = collected.down_payment_available,
            property_price       = collected.property_price,
            tenure_years         = collected.tenure_years or 20,
            annual_interest_rate = collected.annual_interest_rate or 0.0875,
            age                  = collected.age,
            state                = "maharashtra",
            property_type        = PropertyType(collected.property_type or "ready_to_move"),
            area_sqft            = collected.area_sqft,
            session_id           = session_id,
        )

        # ── Step 2: Mumbai costs ──────────────────────────────────────────────
        mumbai_costs = calculate_mumbai_true_cost(
            base_price       = collected.property_price,
            area_sqft        = collected.area_sqft,
            floor_number     = collected.floor_number or 5,
            property_type    = collected.property_type or "ready_to_move",
            facing           = collected.facing or "internal",
            parking_included = collected.parking_included or False,
            parking_cost     = collected.parking_cost or 300000,
            loan_amount      = loan_amount,
            locality         = collected.locality or "mumbai",
            owner_gender     = collected.owner_gender or "male",
        )

        # Store for PDF generation later
        session["mumbai_costs"] = mumbai_costs

        # ── Step 3: Deterministic pipeline ───────────────────────────────────
        financial_reality = calculate_affordability(user_input)
        all_scenarios     = run_all_scenarios(user_input, financial_reality)
        risk_score        = calculate_risk_score(
            financial_reality=financial_reality,
            all_scenarios=all_scenarios,
            age=user_input.age,
            tenure_years=user_input.tenure_years,
        )

        # ── Step 4: Build behavioral intake from conversation ─────────────────
        # Infer behavioral signals from what the user said during intake
        history        = session.get("history", [])
        user_messages  = [m["content"] for m in history if m["role"] == ChatRole.USER]
        conversation_text = " ".join(user_messages).lower()

        behavioral_answers = _infer_behavioral_answers(
            conversation_text, session_id, collected
        )

        behavioral_intake = BehavioralIntake(
            session_id=session_id,
            answers=behavioral_answers,
        )

        # ── Step 5: AI orchestrator ───────────────────────────────────────────
        deterministic_results = {
            "india_cost_breakdown": {
                # Map mumbai_costs fields to existing india_cost_breakdown schema
                # so the existing agents don't need changes
                "base_price":           mumbai_costs.base_price,
                "stamp_duty":           mumbai_costs.stamp_duty,
                "stamp_duty_rate":      0.05,
                "registration_fee":     mumbai_costs.registration_fee,
                "gst":                  mumbai_costs.gst,
                "gst_applicable":       mumbai_costs.is_under_construction,
                "maintenance_deposit":  mumbai_costs.maintenance_deposit,
                "loan_processing_fee":  mumbai_costs.loan_processing_fee,
                "legal_charges":        mumbai_costs.total_legal_costs,
                "true_total_cost":      mumbai_costs.true_total_acquisition_cost,
                "tax_benefit_80c":      150000.0,
                "tax_benefit_24b":      200000.0,
            },
            "financial_reality": financial_reality.model_dump(),
            "all_scenarios":     all_scenarios.model_dump(),
            "risk_score":        risk_score.model_dump(),
        }

        if orchestrator:
            await orchestrator.analyze(
                session_id=session_id,
                user_input=user_input,
                behavioral_intake=behavioral_intake,
                deterministic_results=deterministic_results,
            )
            print(f"[Pipeline] Analysis complete for session {session_id}")
        else:
            print(f"[Pipeline] Orchestrator not available — deterministic only")

        # Analysis done — roundtable can now start
        session["status"] = ChatStatus.ROUNDTABLE

    except Exception as e:
        print(f"[Pipeline] Error for session {session_id}: {e}")
        session["status"] = ChatStatus.ERROR
        session["error"]  = str(e)


def _infer_behavioral_answers(
    conversation_text: str,
    session_id: str,
    collected: CollectedData,
) -> list:
    """
    Infer behavioral bias signals from the conversation.
    Heuristic — not a survey. Looks for keywords that indicate
    FOMO, anchoring, social pressure, optimism bias, denial.
    Returns a list of BehavioralAnswer objects.
    """
    answers = []

    # FOMO signals
    fomo_keywords = ["urgent", "last", "going fast", "price rising", "won't last",
                     "everyone buying", "limited", "hurry", "deadline"]
    fomo_detected = any(k in conversation_text for k in fomo_keywords)
    answers.append(BehavioralAnswer(
        question_id=1,
        question="Are you feeling time pressure to buy?",
        answer="Yes, prices are rising and I feel urgency" if fomo_detected else "No particular urgency",
        bias_signal="FOMO"
    ))

    # Emotional commitment / anchoring
    anchor_keywords = ["love this", "dream home", "perfect", "already decided",
                       "set my heart", "this is the one", "fell in love"]
    anchored = any(k in conversation_text for k in anchor_keywords)
    answers.append(BehavioralAnswer(
        question_id=2,
        question="Have you emotionally committed to this specific property?",
        answer="Yes, I'm very attached to this property" if anchored else "Still evaluating options",
        bias_signal="anchoring"
    ))

    # Social pressure
    social_keywords = ["friends bought", "everyone has", "colleague", "family pressure",
                       "parents want", "relatives bought", "neighbour"]
    social_pressure = any(k in conversation_text for k in social_keywords)
    answers.append(BehavioralAnswer(
        question_id=3,
        question="Is social or family pressure influencing this decision?",
        answer="Yes, family and friends have been buying" if social_pressure else "No significant social pressure",
        bias_signal="social_pressure"
    ))

    # Optimism bias — stretching budget
    stretch_keywords = ["will get promoted", "income will grow", "bonus expected",
                        "stretch", "manage somehow", "figure it out"]
    optimistic = any(k in conversation_text for k in stretch_keywords)
    answers.append(BehavioralAnswer(
        question_id=4,
        question="Are you counting on future income growth to make this work?",
        answer="Yes, expecting significant income growth" if optimistic else "Working with current income",
        bias_signal="optimism_bias"
    ))

    # Denial / risk blindness
    denial_keywords = ["job is secure", "nothing will go wrong", "i'll be fine",
                       "won't lose job", "stable job", "government job"]
    denial = any(k in conversation_text for k in denial_keywords)
    answers.append(BehavioralAnswer(
        question_id=5,
        question="Have you considered what happens if your income drops?",
        answer="Not really, my job feels very secure" if denial else "Yes, I've thought about downside scenarios",
        bias_signal="denial"
    ))

    return answers


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)