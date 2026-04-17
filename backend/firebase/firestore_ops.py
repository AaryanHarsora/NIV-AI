"""
Every Firestore read and write operation in the system.

Dev 2 calls exactly these functions:
    save_discussion_message(session_id, message)  — persist roundtable messages
    get_session(session_id)                       — load session context
    save_verdict(session_id, verdict)             — persist final verdict
    update_session(session_id, updates)           — merge updates into session

All other functions are used by Dev 1's routes in main.py.
"""
import uuid
from datetime import datetime, timezone
from firebase.firebase_admin import db


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------

def create_session(user_id: str, title: str, city: str, state: str) -> str:
    """
    Creates a new session document. Returns the session_id.
    """
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    session_data = {
        "session_id": session_id,
        "user_id": user_id,
        "title": title,
        "city": city,
        "state": state,
        "status": "started",
        "created_at": now,
        "updated_at": now,
    }
    db.collection("sessions").document(session_id).set(session_data)
    return session_id


def get_session(session_id: str) -> dict:
    """
    Retrieves a session document by ID.
    Returns the session dict or None if not found.

    DEV 2 calls this to load context for agent calls.
    """
    doc = db.collection("sessions").document(session_id).get()
    if doc.exists:
        return doc.to_dict()
    return None


def update_session(session_id: str, updates: dict) -> None:
    """
    Merges updates into an existing session document.
    Always refreshes the updated_at timestamp.

    DEV 2 calls this to persist agent outputs.
    """
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    db.collection("sessions").document(session_id).update(updates)


# ---------------------------------------------------------------------------
# Behavioral intake
# ---------------------------------------------------------------------------

def save_behavioral_intake(session_id: str, answers: list) -> None:
    """
    Saves each behavioral answer as a sub-document under the session.
    """
    for answer in answers:
        q_id = str(answer.get("question_id", uuid.uuid4()))
        db.collection("sessions").document(session_id) \
          .collection("behavioral_intake").document(q_id).set(answer)

    update_session(session_id, {"status": "behavioral_done"})


def get_behavioral_intake(session_id: str) -> dict:
    """
    Retrieves all behavioral intake answers for a session.

    DEV 2 calls this when loading context for orchestrator.analyze().

    Returns:
        dict matching BehavioralIntake shape:
        {
            "session_id": str,
            "answers": List[dict]   # each dict matches BehavioralAnswer schema
        }
    """
    docs = db.collection("sessions").document(session_id) \
             .collection("behavioral_intake").stream()
    answers = []
    for doc in docs:
        answers.append(doc.to_dict())
    return {"session_id": session_id, "answers": answers}


# ---------------------------------------------------------------------------
# Financial inputs
# ---------------------------------------------------------------------------

def save_financial_inputs(session_id: str, inputs: dict) -> None:
    """
    Saves the financial input form data under the session.
    """
    db.collection("sessions").document(session_id) \
      .collection("financial_inputs").document("latest").set(inputs)

    # Also update the session-level metadata for history listing
    update_session(session_id, {
        "property_price": inputs.get("property_price"),
        "state": inputs.get("state"),
        "title": f"₹{inputs.get('property_price', 0) / 100000:.0f}L in {inputs.get('state', 'India')}",
    })


# ---------------------------------------------------------------------------
# Simulation results
# ---------------------------------------------------------------------------

def save_simulation_results(session_id: str, results: dict) -> None:
    """
    Saves all deterministic agent outputs under the session.
    results must contain: financial_reality, all_scenarios, risk_score, india_cost_breakdown
    """
    db.collection("sessions").document(session_id) \
      .collection("simulation_results").document("latest").set(results)

    # Update session-level risk label for history listing
    risk_label = None
    if results.get("risk_score"):
        risk_label = results["risk_score"].get("risk_label")
    update_session(session_id, {"risk_label": risk_label})


# ---------------------------------------------------------------------------
# Discussion messages  (DEV 2 calls this)
# ---------------------------------------------------------------------------

def save_discussion_message(session_id: str, message: dict) -> None:
    """
    Appends a single roundtable message to the session's discussion_transcript
    subcollection. DEV 2 calls this from the discussion engine.

    Args:
        session_id: The session this message belongs to.
        message: A dict matching the AgentMessage schema:
            {
                "agent": str,
                "message_type": str,
                "content": str,
                "round": int,
                "timestamp": str,
                "directed_at": str | None
            }
    """
    db.collection("sessions").document(session_id) \
      .collection("discussion_transcript").add(message)


# ---------------------------------------------------------------------------
# Verdict  (DEV 2 calls this)
# ---------------------------------------------------------------------------

def save_verdict(session_id: str, verdict: dict) -> None:
    """
    Saves the final verdict under the session.
    DEV 2 calls this after the Decision Synthesizer produces the verdict.
    """
    db.collection("sessions").document(session_id) \
      .collection("verdict").document("latest").set(verdict)

    # Update session-level summary
    update_session(session_id, {
        "status": "completed",
        "verdict_summary": verdict.get("final_narrative", "")[:200],
    })


# ---------------------------------------------------------------------------
# Session history
# ---------------------------------------------------------------------------

def get_session_history(user_id: str) -> list:
    """
    Returns a list of session summaries for a user, most recent first.
    """
    docs = (
        db.collection("sessions")
        .where("user_id", "==", user_id)
        .order_by("created_at", direction="DESCENDING")
        .stream()
    )
    sessions = []
    for doc in docs:
        data = doc.to_dict()
        sessions.append({
            "session_id": data.get("session_id"),
            "title": data.get("title", "Untitled"),
            "created_at": data.get("created_at"),
            "risk_label": data.get("risk_label"),
            "verdict_summary": data.get("verdict_summary"),
            "property_price": data.get("property_price"),
            "city": data.get("city"),
        })
    return sessions


# ---------------------------------------------------------------------------
# Report persistence
# ---------------------------------------------------------------------------

def save_report_url(session_id: str, gcs_url: str) -> None:
    """Saves the signed GCS URL for a generated PDF report."""
    now = datetime.now(timezone.utc).isoformat()
    db.collection("sessions").document(session_id) \
      .collection("reports").document("latest").set({
          "gcs_url": gcs_url,
          "generated_at": now,
      })


def get_report_url(session_id: str) -> str:
    """Returns the stored report URL if one exists, else None."""
    doc = db.collection("sessions").document(session_id) \
        .collection("reports").document("latest").get()
    if doc.exists:
        return doc.to_dict().get("gcs_url")
    return None
