"""
Analysis endpoints:
  POST /api/v1/analyze         — full 6-agent pipeline (rate-limited: 5/10min/IP)
  GET  /api/v1/calculate       — headless math engine, no LLM (rate-limited: 30/min/IP)
  GET  /api/v1/market/rates    — static home-loan rate reference (<50ms, no HTTP calls)
  POST /api/v1/tools/delta     — headless delta between two param sets (<50ms, no LLM)
  GET  /api/v1/risk/envelope   — affordability envelope from income + savings profile
"""
import json
import logging
import os
import time
import traceback
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.agents.pipeline import run_analysis
from backend.calculations.benchmarks import get_area_benchmark_result
from backend.calculations.delta_engine import compute_delta
from backend.calculations.financial import compute_all
from backend.calculations.risk_engine import (
    classify_financial_state,
    compute_affordability_envelope,
    compute_confidence_score,
    compute_stability_score,
    compute_survival_timeline,
    evaluate_risk,
    get_action_plan,
)
from backend.models.input_models import AnalysisRequest
from backend.utils.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["analysis"])

DEMO_API_KEY: str | None = os.getenv("DEMO_API_KEY")
_MARKET_RATES_PATH = Path(__file__).parent.parent / "data" / "market_rates.json"
_MARKET_RATES_FALLBACK = {
    "sbi_rate": 8.50,
    "hdfc_rate": 8.70,
    "icici_rate": 8.75,
    "axis_rate": 8.85,
    "kotak_rate": 8.90,
    "min_rate": 8.50,
    "max_rate": 9.90,
    "rbi_repo_rate": 6.50,
    "last_updated": "April 2026",
    "source": "Static reference — verify with your bank",
    "disclaimer": "Rates are indicative. Final rate depends on CIBIL score and bank policy.",
}


def _check_api_key(request: Request) -> None:
    """Enforce X-API-Key header when DEMO_API_KEY env var is set."""
    if DEMO_API_KEY and request.headers.get("X-API-Key") != DEMO_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header.")


def _build_computed(body: AnalysisRequest):
    """
    Re-runs compute_all() from an AnalysisRequest so the risk engine has a
    ComputedNumbers object. Mirrors the benchmark look-up done in /calculate.
    """
    fin = body.financial
    prop = body.property
    bm = get_area_benchmark_result(prop.location_area)
    maintenance = bm.data.maintenance_typical if bm.data else 5.5
    rental_yield = bm.data.rental_yield_pct if bm.data else 2.5
    equivalent_rent = round(prop.property_price * (rental_yield / 100) / 12, 2)
    monthly_expenses = fin.monthly_expenses if fin.monthly_expenses > 0 else round(fin.monthly_income * 0.40, 2)

    return compute_all(
        monthly_income=fin.monthly_income,
        spouse_income=fin.spouse_income,
        existing_emis=fin.existing_emis,
        monthly_expenses=monthly_expenses,
        liquid_savings=fin.liquid_savings,
        dependents=fin.dependents,
        property_price=prop.property_price,
        down_payment=prop.down_payment_available,
        loan_tenure_years=prop.loan_tenure_years,
        interest_rate=prop.expected_interest_rate,
        carpet_area_sqft=prop.carpet_area_sqft,
        buyer_gender=prop.buyer_gender.value,
        is_ready_to_move=prop.is_ready_to_move,
        maintenance_per_sqft=maintenance,
        equivalent_rent=equivalent_rent,
        commute_distance_km=prop.commute_distance_km,
    ), fin, prop


# ---------------------------------------------------------------------------
# POST /api/v1/analyze
# ---------------------------------------------------------------------------

@router.post("/analyze")
@limiter.limit("5/10 minutes")
async def analyze(request: Request, body: AnalysisRequest):
    """
    Run the full 6-agent analysis pipeline.

    Rate-limited to 5 requests per 10 minutes per IP. If DEMO_API_KEY env var is set,
    requires a matching X-API-Key header (disabled in local development).

    In addition to the LLM pipeline result, the response includes deterministic
    risk and affordability metrics computed from the same input parameters.
    """
    _check_api_key(request)
    try:
        raw_input = {
            "financial": body.financial.model_dump(),
            "property": body.property.model_dump(),
            "output_language": body.output_language.value,
            "behavioral_checklist_responses": body.behavioral_checklist_responses,
        }
        raw_input["financial"]["employment_type"] = body.financial.employment_type.value
        raw_input["property"]["configuration"] = body.property.configuration.value
        raw_input["property"]["buyer_gender"] = body.property.buyer_gender.value

        result = await run_analysis(raw_input)

        # Deterministic enrichment — no LLM, no latency cost
        computed, fin, prop = _build_computed(body)
        monthly_expenses = fin.monthly_expenses if fin.monthly_expenses > 0 else round(fin.monthly_income * 0.40, 2)

        result["risk_evaluation"] = evaluate_risk(computed)
        result["financial_state"] = classify_financial_state(computed)
        result["confidence_score_details"] = compute_confidence_score(computed)
        result["stability_score"] = compute_stability_score(computed)
        result["affordability_envelope"] = compute_affordability_envelope(
            monthly_income=fin.monthly_income,
            spouse_income=fin.spouse_income,
            existing_emis=fin.existing_emis,
            monthly_expenses=monthly_expenses,
            liquid_savings=fin.liquid_savings,
            interest_rate=prop.expected_interest_rate,
            loan_tenure_years=prop.loan_tenure_years,
        )
        result["survival_timeline"] = compute_survival_timeline(computed)
        result["action_plan"] = get_action_plan(computed)

        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=f"Service unavailable: {e}")
    except Exception as e:
        logger.error("Unexpected error: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail="Unexpected error. Please try again.")


# ---------------------------------------------------------------------------
# GET /api/v1/calculate
# ---------------------------------------------------------------------------

class CalculateResponse(BaseModel):
    """Response model for the headless calculate endpoint."""
    loan_amount: float
    monthly_emi: float
    total_loan_payment: float
    total_interest_paid: float
    total_acquisition_cost: float
    stamp_duty: float
    registration: float
    gst: float
    monthly_ownership_cost: float
    monthly_maintenance: float
    emi_to_income_ratio: float
    total_housing_to_income_ratio: float
    down_payment_to_savings_ratio: float
    emergency_runway_months: float
    post_purchase_savings: float
    annual_tax_saving: float
    effective_monthly_cost_after_tax: float
    rent_vs_buy_premium_pct: float
    rent_vs_buy_break_even_years: float
    interiors_estimated_cost: float
    true_total_acquisition_cost: float
    down_payment_opportunity_cost_10yr: float
    annual_commute_cost_estimate: float
    maintenance_5yr_projected_cost: float
    true_monthly_cost_after_all_factors: float
    down_payment: float
    benchmark_available: bool
    response_time_ms: float
    delta: Optional[dict] = None


@router.get("/calculate", response_model=CalculateResponse)
@limiter.limit("30/minute")
async def calculate(
    request: Request,
    monthly_income: float,
    property_price: float,
    down_payment: float,
    carpet_area_sqft: float,
    location_area: str = "Mumbai",
    spouse_income: float = 0.0,
    existing_emis: float = 0.0,
    monthly_expenses: float = 0.0,
    liquid_savings: float = 0.0,
    dependents: int = 0,
    loan_tenure_years: int = 20,
    interest_rate: float = 8.5,
    buyer_gender: str = "male",
    is_ready_to_move: bool = True,
    commute_distance_km: float = 0.0,
    compare_to_down_payment: Optional[float] = None,
):
    """
    Headless math engine — returns all computed financial metrics without running any LLM agents.

    Pass compare_to_down_payment to receive a delta field showing how switching to that
    down payment amount changes every metric. Response time is typically under 100ms.
    """
    t0 = time.perf_counter()

    if monthly_income <= 0:
        raise HTTPException(status_code=422, detail="monthly_income must be greater than 0")
    if property_price <= 100000:
        raise HTTPException(status_code=422, detail="property_price must be greater than 100,000")
    if down_payment >= property_price:
        raise HTTPException(status_code=422, detail="down_payment cannot exceed property_price")
    if buyer_gender not in ("male", "female"):
        raise HTTPException(status_code=422, detail="buyer_gender must be 'male' or 'female'")
    if compare_to_down_payment is not None and compare_to_down_payment >= property_price:
        raise HTTPException(status_code=422, detail="compare_to_down_payment cannot exceed property_price")

    if monthly_expenses <= 0:
        monthly_expenses = round(monthly_income * 0.40, 2)

    bm = get_area_benchmark_result(location_area)
    maintenance = bm.data.maintenance_typical if bm.data else 5.5
    rental_yield = bm.data.rental_yield_pct if bm.data else 2.5
    benchmark_available = bm.coverage_level != "default"
    equivalent_rent = round(property_price * (rental_yield / 100) / 12, 2)

    _common = dict(
        monthly_income=monthly_income,
        spouse_income=spouse_income,
        existing_emis=existing_emis,
        monthly_expenses=monthly_expenses,
        liquid_savings=liquid_savings,
        dependents=dependents,
        property_price=property_price,
        loan_tenure_years=loan_tenure_years,
        interest_rate=interest_rate,
        carpet_area_sqft=carpet_area_sqft,
        buyer_gender=buyer_gender,
        is_ready_to_move=is_ready_to_move,
        maintenance_per_sqft=maintenance,
        equivalent_rent=equivalent_rent,
        commute_distance_km=commute_distance_km,
    )

    computed = compute_all(down_payment=down_payment, **_common)
    result = computed.to_dict()
    result["benchmark_available"] = benchmark_available

    if compare_to_down_payment is not None:
        computed_alt = compute_all(down_payment=compare_to_down_payment, **_common)
        result["delta"] = compute_delta(result, computed_alt.to_dict())
    else:
        result["delta"] = None

    result["response_time_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/market/rates
# ---------------------------------------------------------------------------

@router.get("/market/rates")
async def get_market_rates():
    """
    Returns current home loan market rates.

    Attempts to read from backend/data/market_rates.json.
    If that file is older than 24 hours or missing, returns hardcoded fallback.
    Never makes external HTTP calls — response is always under 50ms.
    """
    try:
        if _MARKET_RATES_PATH.exists():
            age_seconds = time.time() - _MARKET_RATES_PATH.stat().st_mtime
            if age_seconds < 86400:
                return json.loads(_MARKET_RATES_PATH.read_text())
    except Exception:
        pass
    return _MARKET_RATES_FALLBACK


# ---------------------------------------------------------------------------
# POST /api/v1/tools/delta
# ---------------------------------------------------------------------------

class CalculateParams(BaseModel):
    monthly_income: float
    property_price: float
    down_payment: float
    carpet_area_sqft: float
    location_area: str = "Mumbai"
    spouse_income: float = 0.0
    existing_emis: float = 0.0
    monthly_expenses: float = 0.0
    liquid_savings: float = 0.0
    dependents: int = 0
    loan_tenure_years: int = 20
    interest_rate: float = 8.5
    buyer_gender: str = "male"
    is_ready_to_move: bool = True
    commute_distance_km: float = 0.0


class DeltaRequest(BaseModel):
    before: CalculateParams
    after: CalculateParams


def _params_to_computed(p: CalculateParams):
    """Resolve benchmark data and run compute_all() for a CalculateParams object."""
    bm = get_area_benchmark_result(p.location_area)
    maintenance = bm.data.maintenance_typical if bm.data else 5.5
    rental_yield = bm.data.rental_yield_pct if bm.data else 2.5
    equivalent_rent = round(p.property_price * (rental_yield / 100) / 12, 2)
    monthly_expenses = p.monthly_expenses if p.monthly_expenses > 0 else round(p.monthly_income * 0.40, 2)

    return compute_all(
        monthly_income=p.monthly_income,
        spouse_income=p.spouse_income,
        existing_emis=p.existing_emis,
        monthly_expenses=monthly_expenses,
        liquid_savings=p.liquid_savings,
        dependents=p.dependents,
        property_price=p.property_price,
        down_payment=p.down_payment,
        loan_tenure_years=p.loan_tenure_years,
        interest_rate=p.interest_rate,
        carpet_area_sqft=p.carpet_area_sqft,
        buyer_gender=p.buyer_gender,
        is_ready_to_move=p.is_ready_to_move,
        maintenance_per_sqft=maintenance,
        equivalent_rent=equivalent_rent,
        commute_distance_km=p.commute_distance_km,
    )


@router.post("/tools/delta")
async def tools_delta(body: DeltaRequest):
    """
    Headless delta computation — takes two sets of params, returns the delta between them.
    Used by sensitivity sliders. No LLM. Response under 50ms.
    """
    before_dict = _params_to_computed(body.before).to_dict()
    after_dict = _params_to_computed(body.after).to_dict()
    return compute_delta(before_dict, after_dict)


# ---------------------------------------------------------------------------
# GET /api/v1/risk/envelope
# ---------------------------------------------------------------------------

@router.get("/risk/envelope")
async def risk_envelope(
    monthly_income: float,
    liquid_savings: float,
    spouse_income: float = 0.0,
    existing_emis: float = 0.0,
    monthly_expenses: float = 0.0,
    interest_rate: float = 8.5,
    loan_tenure_years: int = 20,
):
    """
    Returns the affordability envelope for a given income and savings profile.

    No property params needed — powers the 'safe range' guidance shown before
    the user picks a specific property. No LLM. Response under 50ms.
    """
    if monthly_income <= 0:
        raise HTTPException(status_code=422, detail="monthly_income must be greater than 0")

    if monthly_expenses <= 0:
        monthly_expenses = round(monthly_income * 0.40, 2)

    return compute_affordability_envelope(
        monthly_income=monthly_income,
        spouse_income=spouse_income,
        existing_emis=existing_emis,
        monthly_expenses=monthly_expenses,
        liquid_savings=liquid_savings,
        interest_rate=interest_rate,
        loan_tenure_years=loan_tenure_years,
    )
