"""
FastAPI application — the HTTP layer for NIV AI Home Buying Advisor.

This file is deliberately thin:
- Receives requests, validates auth, calls orchestrator functions, returns responses.
- No business logic. No financial math inside routes. No AI calls.
- Routing and validation only.
"""
import os
import json
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware

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
    save_report_url,
    get_report_url,
)
from schemas.schemas import (
    UserInput,
    BehavioralIntake,
    ConversationMessage,
    APIResponse,
    AnalysisResponse,
    SessionStartResponse,
    ConversationResponse,
    ReportOutput,
    PresentationOutput,
    VerdictOutput,
)
from engines.india_defaults import calculate_true_total_cost
from agents.deterministic.financial_reality import calculate_affordability
from agents.deterministic.scenario_simulation import run_all_scenarios
from agents.deterministic.risk_scorer import calculate_risk_score
from engines.pdf_generator import generate_pdf
from storage.gcs_client import upload_pdf


# ---------------------------------------------------------------------------
# App initialization
# ---------------------------------------------------------------------------

app = FastAPI(
    title="NIV AI — Home Buying Advisor API",
    description="Risk-aware home buying decision intelligence for Indian families",
    version="1.0.0",
)

# CORS — allow frontend origin. In development allow all origins.
frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Orchestrator — single instance, initialized once
orchestrator = None


@app.on_event("startup")
async def startup_event():
    """Initialize Firebase and Orchestrator on app startup."""
    global orchestrator

    try:
        initialize_firebase()
        print("✅ Firebase initialized")
    except Exception as e:
        print(f"⚠️ Firebase init failed: {e}")

    try:
        from agents.orchestration.orchestrator import Orchestrator
        orchestrator = Orchestrator()
        print("✅ Orchestrator initialized")
    except Exception as e:
        print(f"⚠️ Orchestrator init failed (Dev 2 code may not be ready): {e}")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "niv-ai-home-buying-advisor", "version": "1.0.0"}


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

@app.post("/session/start", response_model=APIResponse)
async def start_session(uid: str = Depends(verify_token)):
    """Creates a new analysis session for the authenticated user."""
    session_id = create_session(
        user_id=uid,
        title="New Analysis",
        city="",
        state="",
    )
    now = datetime.now(timezone.utc).isoformat()
    return APIResponse(
        success=True,
        message="Session created",
        data=SessionStartResponse(
            session_id=session_id,
            user_id=uid,
            created_at=now,
        ).model_dump(),
    )


@app.get("/session/{session_id}", response_model=APIResponse)
async def get_session_route(session_id: str, uid: str = Depends(verify_token)):
    """Retrieves a session by ID. User must own the session."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.get("user_id") != uid:
        raise HTTPException(status_code=403, detail="Access denied")
    return APIResponse(success=True, message="Session retrieved", data=session)


@app.get("/session/history/{user_id}", response_model=APIResponse)
async def get_history_route(user_id: str, uid: str = Depends(verify_token)):
    """Returns all sessions for a user, most recent first."""
    if user_id != uid:
        raise HTTPException(status_code=403, detail="Access denied")
    sessions = get_session_history(user_id)
    return APIResponse(success=True, message="History retrieved", data=sessions)


# ---------------------------------------------------------------------------
# Behavioral intake
# ---------------------------------------------------------------------------

@app.post("/behavioral/{session_id}", response_model=APIResponse)
async def save_behavioral_route(
    session_id: str,
    intake: BehavioralIntake,
    uid: str = Depends(verify_token),
):
    """Saves the 7 behavioral questionnaire answers for a session."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.get("user_id") != uid:
        raise HTTPException(status_code=403, detail="Access denied")

    save_behavioral_intake(session_id, [a.model_dump() for a in intake.answers])
    return APIResponse(success=True, message="Behavioral intake saved")


# ---------------------------------------------------------------------------
# Analysis — the main pipeline
# ---------------------------------------------------------------------------

@app.post("/analyze/{session_id}", response_model=APIResponse)
async def analyze_route(
    session_id: str,
    user_input: UserInput,
    uid: str = Depends(verify_token),
):
    """
    Runs the full analysis pipeline:
    1. Validate auth and session ownership
    2. Save financial inputs to Firestore
    3. Run deterministic agents (india defaults, financial reality, scenarios, risk score)
    4. Bundle deterministic results
    5. Get behavioral intake from Firestore
    6. Call orchestrator.analyze() for AI agents
    7. Return AnalysisResponse
    """
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.get("user_id") != uid:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        # Save financial inputs
        save_financial_inputs(session_id, user_input.model_dump())

        # --- Run deterministic agents ---
        loan_amount = user_input.property_price - user_input.down_payment
        if loan_amount < 0:
            loan_amount = 0.0

        india_costs = calculate_true_total_cost(
            base_price=user_input.property_price,
            state=user_input.state,
            property_type=user_input.property_type.value,
            loan_amount=loan_amount,
            area_sqft=user_input.area_sqft if user_input.area_sqft else 1000,
        )

        financial_reality = calculate_affordability(user_input)
        all_scenarios = run_all_scenarios(user_input, financial_reality)
        risk_score = calculate_risk_score(
            financial_reality=financial_reality,
            all_scenarios=all_scenarios,
            age=user_input.age,
            tenure_years=user_input.tenure_years,
        )

        # Bundle deterministic results for Dev 2's orchestrator
        deterministic_results = {
            "india_cost_breakdown": india_costs.model_dump(),
            "financial_reality": financial_reality.model_dump(),
            "all_scenarios": all_scenarios.model_dump(),
            "risk_score": risk_score.model_dump(),
        }

        # Save to Firestore
        save_simulation_results(session_id, deterministic_results)

        # --- Call Dev 2's orchestrator ---
        if orchestrator:
            # Get behavioral intake from Firestore
            intake_data = get_behavioral_intake(session_id)
            answers = intake_data.get("answers", [])

            behavioral_intake = BehavioralIntake(
                session_id=session_id,
                answers=answers,
            )

            analysis_response = await orchestrator.analyze(
                session_id=session_id,
                user_input=user_input,
                behavioral_intake=behavioral_intake,
                deterministic_results=deterministic_results,
            )
            return APIResponse(
                success=True,
                message="Analysis complete",
                data=analysis_response.model_dump(),
            )
        else:
            # Orchestrator not available — return deterministic results only
            return APIResponse(
                success=True,
                message="Deterministic analysis complete (AI agents not available)",
                data={
                    "session_id": session_id,
                    "financial_reality": financial_reality.model_dump(),
                    "all_scenarios": all_scenarios.model_dump(),
                    "risk_score": risk_score.model_dump(),
                },
            )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


# ---------------------------------------------------------------------------
# Conversation — follow-up turns
# ---------------------------------------------------------------------------

@app.post("/conversation/{session_id}", response_model=APIResponse)
async def conversation_route(
    session_id: str,
    message: ConversationMessage,
    uid: str = Depends(verify_token),
):
    """Handles a follow-up message. Calls orchestrator.continue_conversation()."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.get("user_id") != uid:
        raise HTTPException(status_code=403, detail="Access denied")

    if not orchestrator:
        raise HTTPException(status_code=501, detail="AI agents not available")

    try:
        result = await orchestrator.continue_conversation(
            session_id=session_id,
            message=message.message,
        )
        return APIResponse(
            success=True,
            message="Conversation processed",
            data=result.model_dump(),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Conversation failed: {str(e)}")


# ---------------------------------------------------------------------------
# WebSocket — live roundtable streaming
# ---------------------------------------------------------------------------

@app.websocket("/roundtable/{session_id}")
async def roundtable_ws(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(""),
):
    """
    WebSocket endpoint for live roundtable streaming.
    Dev 3 connects as: ws://<host>/roundtable/<session_id>?token=<firebase_token>
    """
    # Verify auth token
    try:
        decoded = firebase_auth.verify_id_token(token)
        user_uid = decoded["uid"]
    except Exception:
        await websocket.close(code=4001, reason="Invalid token")
        return

    # Verify session ownership
    session = get_session(session_id)
    if not session or session.get("user_id") != user_uid:
        await websocket.close(code=4003, reason="Access denied")
        return

    await websocket.accept()

    if not orchestrator:
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "Roundtable engine not available",
            "recoverable": False,
        }))
        await websocket.close()
        return

    try:
        await orchestrator.run_roundtable(
            session_id=session_id,
            websocket=websocket,
        )
    except WebSocketDisconnect:
        print(f"WebSocket disconnected: session {session_id}")
    except Exception as e:
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
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


# ---------------------------------------------------------------------------
# PDF report
# ---------------------------------------------------------------------------

@app.get("/report/{session_id}", response_model=APIResponse)
async def get_report_route(session_id: str, uid: str = Depends(verify_token)):
    """
    Generates or retrieves a PDF report for the session.
    Returns a signed GCS URL valid for 7 days.
    """
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.get("user_id") != uid:
        raise HTTPException(status_code=403, detail="Access denied")

    # Check for existing report
    existing_url = get_report_url(session_id)
    if existing_url:
        return APIResponse(
            success=True,
            message="Report already generated",
            data=ReportOutput(
                session_id=session_id,
                gcs_url=existing_url,
                generated_at=datetime.now(timezone.utc).isoformat(),
            ).model_dump(),
        )

    # Get presentation and verdict from Firestore simulation results
    from firebase.firebase_admin import db as firestore_db
    sim_doc = firestore_db.collection("sessions").document(session_id) \
        .collection("simulation_results").document("latest").get()
    verdict_doc = firestore_db.collection("sessions").document(session_id) \
        .collection("verdict").document("latest").get()

    if not verdict_doc.exists:
        raise HTTPException(status_code=400, detail="Analysis not complete. Run /analyze and roundtable first.")

    try:
        verdict_data = verdict_doc.to_dict()
        verdict_output = VerdictOutput(**verdict_data)

        # Get presentation from session (set by orchestrator)
        # The orchestrator stores presentation in the blackboard
        # For PDF we need it — check if it's available in session
        session_data = get_session(session_id)
        if not session_data:
            raise HTTPException(status_code=404, detail="Session not found")

        # Try to get presentation from orchestrator's in-memory state
        presentation_output = None
        if orchestrator and session_id in orchestrator._blackboards:
            bb_state = orchestrator._blackboards[session_id].state
            if bb_state.presentation:
                presentation_output = bb_state.presentation

        if not presentation_output:
            raise HTTPException(
                status_code=400,
                detail="Presentation data not available. Run full analysis with roundtable first.",
            )

        pdf_bytes = generate_pdf(session_id, presentation_output, verdict_output)
        gcs_url = upload_pdf(session_id, pdf_bytes)
        save_report_url(session_id, gcs_url)

        return APIResponse(
            success=True,
            message="Report generated",
            data=ReportOutput(
                session_id=session_id,
                gcs_url=gcs_url,
                generated_at=datetime.now(timezone.utc).isoformat(),
            ).model_dump(),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {str(e)}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
