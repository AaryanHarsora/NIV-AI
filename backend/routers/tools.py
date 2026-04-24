"""
Tool endpoints for NIV AI — counter-offer generator, bank email composer,
GST health checker, OC/CC status checker, and market intelligence tools.
"""

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.utils.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")


# ─────────────────────────────────────────────────────────────────
# PYDANTIC MODELS
# ─────────────────────────────────────────────────────────────────

class CounterOfferRequest(BaseModel):
    """Request body for counter-offer PDF generation."""

    report: dict
    input: dict
    buyer_name: str = "Home Buyer"


class BankEmailRequest(BaseModel):
    """Request body for bank email generation."""

    computed_numbers: dict
    raw_input: dict
    target_bank: str = "HDFC/SBI/ICICI"


class OcStatusRequest(BaseModel):
    """Request body for standalone OC/CC status check."""

    is_ready_to_move: bool
    possession_date: str = ""
    is_rera_registered: Optional[bool] = None
    builder_name: str = ""
    rera_data: Optional[dict] = None


# ─────────────────────────────────────────────────────────────────
# FEATURE 1: COUNTER-OFFER PDF
# ─────────────────────────────────────────────────────────────────

@router.post("/tools/counter-offer")
@limiter.limit("10/hour")
async def generate_counter_offer(request: Request, body: CounterOfferRequest):
    """
    Generates and returns a PDF counter-offer negotiation letter.

    Takes the report data and property input, computes the justified
    counter-offer price deterministically, and returns a downloadable PDF.

    Args:
        request: FastAPI request (used by rate limiter).
        body: CounterOfferRequest with report, input, and buyer_name.

    Returns:
        StreamingResponse with PDF bytes, content-type application/pdf.
    """
    from backend.documents.counter_offer import (
        CounterOfferData,
        compute_counter_offer_price,
        generate_counter_offer_pdf,
    )

    try:
        report = body.report
        raw = body.input
        prop = raw.get("property", {})
        pa = report.get("property_assessment", {})
        pv = pa.get("price_assessment", {})

        property_price = float(prop.get("property_price", 0))
        premium_pct = float(pv.get("premium_over_market_pct", 0))
        property_flags = pa.get("property_flags", [])
        rera_data = pa.get("rera_data", {}) or {}
        rera_complaint_count = rera_data.get("complaint_count")
        rera_registered = prop.get("is_rera_registered")

        counter_price, discount_pct, justifications = compute_counter_offer_price(
            property_price=property_price,
            premium_over_market_pct=premium_pct,
            property_flags=property_flags,
            rera_complaint_count=rera_complaint_count,
        )

        computed = report.get("computed_numbers", {})
        data = CounterOfferData(
            buyer_name=body.buyer_name,
            builder_name=prop.get("builder_name") or "Builder / Developer",
            property_location=prop.get("location_area", "Mumbai"),
            property_price=property_price,
            configuration=prop.get("configuration", "2BHK"),
            carpet_area_sqft=float(prop.get("carpet_area_sqft", 650)),
            area_median_per_sqft=float(pv.get("area_median_per_sqft", 0)),
            price_per_sqft=float(pv.get("price_per_sqft", 0)),
            premium_over_market_pct=premium_pct,
            property_flags=property_flags,
            rera_registered=rera_registered,
            rera_complaint_count=rera_complaint_count,
            possession_date=prop.get("possession_date", ""),
            requested_price=counter_price,
            justified_discount_pct=discount_pct,
            report_date=date.today().strftime("%d %B %Y"),
            justifications=justifications,
        )

        pdf_bytes = generate_counter_offer_pdf(data)
        location_slug = (prop.get("location_area") or "property").replace(" ", "_")
        filename = f"NIV_AI_Counter_Offer_{location_slug}.pdf"

        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except Exception as exc:
        logger.error("Counter-offer generation failed: %s", exc)
        raise HTTPException(500, f"PDF generation failed: {exc}") from exc


# ─────────────────────────────────────────────────────────────────
# FEATURE 2: BANK EMAIL GENERATOR
# ─────────────────────────────────────────────────────────────────

@router.post("/tools/bank-email")
@limiter.limit("20/hour")
async def generate_bank_email(request: Request, body: BankEmailRequest) -> dict:
    """
    Generates a professional home loan inquiry email for the specified bank.
    Single LLM call — returns structured email content ready for copy/send.

    Args:
        request: FastAPI request (used by rate limiter).
        body: BankEmailRequest with computed numbers, raw input, and target bank.

    Returns:
        Dict with subject, body sections, full email text, and FOIR percentage.
    """
    from backend.agents import bank_email_composer
    from backend.llm.client import LLMClient

    try:
        llm = LLMClient()
        result = await bank_email_composer.run(
            llm, body.computed_numbers, body.raw_input, body.target_bank
        )
        fin = body.raw_input.get("financial", {})
        monthly_emi = body.computed_numbers.get("monthly_emi", 0)
        household = fin.get("monthly_income", 0) + fin.get("spouse_income", 0)
        foir = round(
            (fin.get("existing_emis", 0) + monthly_emi) / max(household, 1) * 100, 1
        )
        result["foir_pct"] = foir
        return result
    except Exception as exc:
        logger.error("Bank email generation failed: %s", exc)
        raise HTTPException(500, f"Email generation failed: {exc}") from exc


# ─────────────────────────────────────────────────────────────────
# FEATURE 5: MARKET RATES
# ─────────────────────────────────────────────────────────────────

@router.get("/market/rates")
@limiter.limit("60/hour")
async def get_market_rates(
    request: Request,
    user_rate: Optional[float] = None,
) -> dict:
    """
    Returns current RBI repo rate and home loan rates from top banks.
    Cached 24 hours. If user_rate provided, also returns a rate warning.

    Args:
        request: FastAPI request (used by rate limiter).
        user_rate: Optional user-entered interest rate for comparison.

    Returns:
        Dict with bank rates, RBI repo rate, and optional rate_warning.
    """
    from backend.integrations.bank_rates import check_rate_warning, fetch_market_rates

    rates = await fetch_market_rates()
    result: dict = {
        "rbi_repo_rate": rates.rbi_repo_rate,
        "repo_rate_date": rates.repo_rate_date,
        "banks": [
            {"name": b.bank_name, "min": b.min_rate, "max": b.max_rate}
            for b in rates.bank_rates
        ],
        "market_floor": rates.market_floor,
        "market_ceiling": rates.market_ceiling,
        "market_average": rates.market_average,
        "last_updated": rates.last_updated,
        "data_source": rates.data_source,
        "rate_warning": check_rate_warning(user_rate, rates) if user_rate is not None else None,
    }
    return result


# ─────────────────────────────────────────────────────────────────
# FEATURE 6: RENT ESTIMATOR
# ─────────────────────────────────────────────────────────────────

@router.get("/market/rent")
@limiter.limit("30/hour")
async def get_rent_estimate(
    request: Request,
    area: str,
    configuration: str = "2BHK",
    property_price: float = 0,
) -> dict:
    """
    Returns real-time rental yield estimate for an area and configuration.
    Used to update the rent-vs-buy analysis with live market data.

    Args:
        request: FastAPI request (used by rate limiter).
        area: Mumbai area name (e.g. Andheri West).
        configuration: Property configuration (2BHK, 3BHK etc.).
        property_price: Property price for yield calculation.

    Returns:
        Dict with estimated rent, yield percentage, data source, and confidence.
    """
    from backend.integrations.rent_scraper import estimate_rent

    estimate = await estimate_rent(
        area=area,
        configuration=configuration,
        property_price=property_price,
    )
    return {
        "area": estimate.area,
        "configuration": estimate.configuration,
        "estimated_monthly_rent": estimate.estimated_monthly_rent,
        "rental_yield_pct": estimate.rental_yield_pct,
        "listings_sampled": estimate.listings_sampled,
        "rent_range_min": estimate.rent_range_min,
        "rent_range_max": estimate.rent_range_max,
        "data_source": estimate.data_source,
        "confidence": estimate.confidence,
        "fetched_at": estimate.fetched_at,
    }


# ─────────────────────────────────────────────────────────────────
# FEATURE 9: GST HEALTH CHECK
# ─────────────────────────────────────────────────────────────────

@router.get("/tools/gst-check")
@limiter.limit("20/hour")
async def gst_health_check(request: Request, gstin: str) -> dict:
    """
    Checks a builder's GST registration and filing status.
    Returns risk flag and explanation as one data point for due diligence.

    Args:
        request: FastAPI request (used by rate limiter).
        gstin: Builder's 15-character GSTIN number.

    Returns:
        Dict with registration status, risk flag, and explanation.
    """
    from backend.integrations.gst_checker import check_gstin, validate_gstin_format

    gstin = gstin.strip().upper()
    if not validate_gstin_format(gstin):
        raise HTTPException(
            422,
            "Invalid GSTIN format. A valid GSTIN is 15 characters — "
            "e.g. 27AAXXX1234X1Z5 (2-digit state code + PAN + 1 + Z + 1).",
        )

    result = await check_gstin(gstin)
    return {
        "gstin": result.gstin,
        "business_name": result.business_name,
        "registration_status": result.registration_status,
        "last_return_filed": result.last_return_filed,
        "state": result.state,
        "business_type": result.business_type,
        "risk_flag": result.risk_flag,
        "risk_explanation": result.risk_explanation,
        "data_source": result.data_source,
    }


# ─────────────────────────────────────────────────────────────────
# FEATURE 10: OC/CC STATUS CHECK
# ─────────────────────────────────────────────────────────────────

@router.post("/tools/oc-status")
@limiter.limit("30/hour")
async def check_oc_status(request: Request, body: OcStatusRequest) -> dict:
    """
    Standalone OC/CC status check without running the full pipeline.
    Returns deterministic risk assessment based on property metadata.

    Args:
        request: FastAPI request (used by rate limiter).
        body: OcStatusRequest with property details.

    Returns:
        Dict with risk_level, risk_flags, legal_implications, and recommended_actions.
    """
    from backend.calculations.legal_flags import assess_oc_cc_status

    result = assess_oc_cc_status(
        is_ready_to_move=body.is_ready_to_move,
        possession_date=body.possession_date,
        is_rera_registered=body.is_rera_registered,
        builder_name=body.builder_name,
        rera_data=body.rera_data,
    )
    return {
        "oc_status": result.oc_status,
        "cc_status": result.cc_status,
        "risk_level": result.risk_level,
        "risk_flags": result.risk_flags,
        "legal_implications": result.legal_implications,
        "recommended_actions": result.recommended_actions,
        "overall_note": result.overall_note,
    }
