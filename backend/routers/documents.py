"""
Document upload and parsing endpoints for NIV AI.

Handles: RERA QR scanner, Encumbrance Certificate parser,
Loan Sanction Letter OCR, and document analysis results.
All endpoints accept multipart/form-data file uploads.
Max file size: controlled by MAX_UPLOAD_SIZE_MB env var (default: 10MB).
"""
import io
import logging
import os
import re

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from backend.utils.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "10"))
DOCUMENT_ENABLED = os.getenv("DOCUMENT_UPLOAD_ENABLED", "true").lower() == "true"


@router.post("/documents/scan-rera-qr", response_model=None)
@limiter.limit("20/hour")
async def scan_rera_qr(request: Request, file: UploadFile = File(...)):
    """
    Decodes a RERA QR code from an uploaded image and returns builder data.

    Accepts JPEG, PNG, WEBP image files up to MAX_UPLOAD_MB.
    Decodes QR using pyzbar, extracts RERA registration number,
    then calls fetch_rera_data() with the extracted identifier.

    Args:
        request: FastAPI request (used by rate limiter).
        file: Uploaded image file.

    Returns:
        Dict with extracted_rera_number, rera_data, raw_qr_content, success, error.
    """
    from PIL import Image
    from pyzbar.pyzbar import decode as decode_qr

    from backend.integrations.rera_client import fetch_rera_data

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {MAX_UPLOAD_MB}MB limit")

    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    if file.content_type not in allowed_types:
        raise HTTPException(422, "File must be an image (JPEG, PNG, WEBP)")

    try:
        img = Image.open(io.BytesIO(contents))
        qr_results = decode_qr(img)

        raw_content = ""
        for qr in qr_results:
            raw_content = qr.data.decode("utf-8", errors="ignore")
            break

        rera_number = None
        patterns = [
            r"P\d{11}",
            r"RERA[-/]?\w{8,20}",
            r"registration[_-]?no[:\s]+(\w+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, raw_content, re.IGNORECASE)
            if match:
                rera_number = match.group(0)
                break

        builder_hint = rera_number or raw_content[:100]
        rera_data_obj = None
        if builder_hint:
            rera_data_obj = await fetch_rera_data(builder_hint)

        return {
            "success": bool(raw_content),
            "extracted_rera_number": rera_number,
            "raw_qr_content": raw_content[:200] if raw_content else None,
            "rera_data": {
                "registration_status": rera_data_obj.registration_status,
                "complaint_count": rera_data_obj.complaint_count,
                "risk_score": rera_data_obj.risk_score,
                "risk_label": rera_data_obj.risk_label,
                "data_source": rera_data_obj.data_source,
            } if rera_data_obj else None,
            "error": None if raw_content else "No QR code found in image — ensure image is clear and well-lit.",
        }

    except Exception as exc:
        logger.warning("QR scan failed: %s", exc)
        return {
            "success": False,
            "extracted_rera_number": None,
            "raw_qr_content": None,
            "rera_data": None,
            "error": "Could not decode QR code. Ensure the image is clear and well-lit.",
        }


@router.post("/documents/parse-ec", response_model=None)
@limiter.limit("10/hour")
async def parse_encumbrance_certificate(
    request: Request,
    file: UploadFile = File(...),
    location_area: str = Form(default="Unknown"),
    property_price: float = Form(default=0),
):
    """
    Parses an Encumbrance Certificate PDF and returns structured risk analysis.

    Accepts PDF files only up to MAX_UPLOAD_MB.
    Extracts text with pdfplumber, then uses LLM to identify legal risks.

    Args:
        request: FastAPI request (used by rate limiter).
        file: Uploaded PDF file.
        location_area: Property location for context (form field).
        property_price: Property price in rupees (form field).

    Returns:
        Dict with success flag, analysis dict, and error message.
    """
    from backend.documents.ec_parser import analyze_ec, extract_ec_text
    from backend.llm.client import LLMClient

    if file.content_type != "application/pdf":
        raise HTTPException(422, "File must be a PDF")

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {MAX_UPLOAD_MB}MB limit")

    ec_text = await extract_ec_text(contents)
    if not ec_text.strip():
        return {
            "success": False,
            "error": "Could not extract text from PDF. Ensure it is not a scanned image without OCR.",
            "analysis": None,
        }

    try:
        llm = LLMClient()
        analysis = await analyze_ec(
            llm, ec_text, {"location_area": location_area, "property_price": property_price}
        )
        return {"success": True, "analysis": analysis, "error": None}
    except Exception as exc:
        logger.error("EC analysis failed: %s", exc)
        return {
            "success": False,
            "error": "Analysis failed. Please try again.",
            "analysis": None,
        }


@router.post("/documents/parse-loan-letter", response_model=None)
@limiter.limit("10/hour")
async def parse_loan_letter(request: Request, file: UploadFile = File(...)):
    """
    Extracts key financial terms from a bank loan sanction letter.
    Returns structured data suitable for auto-filling the financial form.

    Accepts PDF or image files up to MAX_UPLOAD_MB.

    Args:
        request: FastAPI request (used by rate limiter).
        file: Uploaded PDF or image file.

    Returns:
        Dict with success flag, extracted loan data, and auto_fill fields.
    """
    from backend.documents.loan_letter_parser import analyze_loan_letter, extract_loan_letter_text
    from backend.llm.client import LLMClient

    allowed = {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/tiff",
    }
    if file.content_type not in allowed:
        raise HTTPException(422, "File must be a PDF or image (JPEG, PNG, WEBP, TIFF)")

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {MAX_UPLOAD_MB}MB limit")

    text = await extract_loan_letter_text(contents, file.content_type or "application/pdf")
    if not text.strip():
        return {
            "success": False,
            "error": "Could not extract text. Ensure the document is not heavily scanned or encrypted.",
            "data": None,
        }

    try:
        llm = LLMClient()
        data = await analyze_loan_letter(llm, text)
        return {"success": True, "data": data, "error": None}
    except Exception as exc:
        logger.error("Loan letter analysis failed: %s", exc)
        return {
            "success": False,
            "error": "Analysis failed. Please try again.",
            "data": None,
        }
