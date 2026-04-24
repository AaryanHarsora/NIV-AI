"""
Builder GST health check for NIV AI.

Queries the GST government portal to verify a builder's registration status
and last return filing date. A lapsed or unfiled GST is a leading indicator
of builder financial stress and potential project abandonment risk.

Controlled by feature availability — graceful degradation on portal failure.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_GST_PORTAL_URL = "https://services.gst.gov.in/services/searchtp"


@dataclass
class GstCheckResult:
    """Result of a GST registration check."""

    gstin: str
    business_name: Optional[str]
    registration_status: str  # "active" | "cancelled" | "suspended" | "unknown"
    last_return_filed: Optional[str]  # YYYY-MM format
    state: Optional[str]
    business_type: Optional[str]
    risk_flag: bool  # True if returns > 3 months stale or cancelled
    risk_explanation: str
    data_source: str  # "gst_portal" | "unavailable"


def validate_gstin_format(gstin: str) -> bool:
    """
    Validates GSTIN format: 15-character alphanumeric.
    Format: 2-digit state code + 10-char PAN + 1-char entity + Z + check digit.

    Args:
        gstin: GSTIN string to validate.

    Returns:
        True if format is valid, False otherwise.
    """
    return bool(re.match(r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}\d{1}Z\d{1}$", gstin.upper()))


def _parse_risk(status: str, last_filed: Optional[str]) -> tuple[bool, str]:
    """
    Determines risk flag and explanation from registration data.

    Args:
        status: Registration status string.
        last_filed: Last return filed date in YYYY-MM format.

    Returns:
        Tuple of (risk_flag: bool, explanation: str)
    """
    if status in ("cancelled", "suspended"):
        return True, f"Builder's GST registration is {status}. This is a significant red flag indicating possible financial or legal issues."

    if last_filed:
        try:
            filed_dt = datetime.strptime(last_filed, "%Y-%m")
            months_stale = (
                (datetime.now().year - filed_dt.year) * 12
                + datetime.now().month
                - filed_dt.month
            )
            if months_stale > 3:
                return (
                    True,
                    f"Builder's last GST return was filed {months_stale} months ago ({last_filed}). "
                    f"Returns more than 3 months overdue indicate potential financial stress.",
                )
            return False, f"GST returns filed recently ({last_filed}). No immediate concern."
        except ValueError:
            pass

    if status == "active":
        return False, "Builder's GST registration is active."

    return False, "GST status could not be fully assessed. Verify with builder directly."


_STATE_CODES = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan",
    "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
    "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura",
    "17": "Meghalaya", "18": "Assam", "19": "West Bengal", "20": "Jharkhand",
    "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman & Diu", "26": "Dadra & Nagar Haveli", "27": "Maharashtra",
    "28": "Andhra Pradesh", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
    "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman & Nicobar",
    "36": "Telangana", "37": "Andhra Pradesh (New)",
}


async def check_gstin(gstin: str) -> GstCheckResult:
    """
    Checks GSTIN registration status via GST portal public API.

    Args:
        gstin: 15-character GSTIN to verify.

    Returns:
        GstCheckResult. Never raises. Returns data_source='unavailable' on failure.
    """
    gstin = gstin.upper().strip()

    if not validate_gstin_format(gstin):
        return GstCheckResult(
            gstin=gstin,
            business_name=None,
            registration_status="unknown",
            last_return_filed=None,
            state=None,
            business_type=None,
            risk_flag=False,
            risk_explanation="Invalid GSTIN format. A valid GSTIN is 15 characters (e.g. 27AAXXX1234X1Z5).",
            data_source="unavailable",
        )

    state_code = gstin[:2]
    state_name = _STATE_CODES.get(state_code)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _GST_PORTAL_URL,
                params={"gstin": gstin},
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            )

            if resp.status_code != 200:
                raise ValueError(f"HTTP {resp.status_code}")

            data = resp.json()
            taxpayer = data.get("taxpayerInfo", {})

            if not taxpayer:
                raise ValueError("No taxpayer data returned")

            status_raw = taxpayer.get("sts", "ACT").upper()
            status_map = {"ACT": "active", "CAN": "cancelled", "SUS": "suspended"}
            status = status_map.get(status_raw[:3], "unknown")

            trade_name = taxpayer.get("tradeNam") or taxpayer.get("lgnm")

            # Parse last filing date
            last_filed = None
            last_upd = taxpayer.get("lastUpdatedAt", "")
            if last_upd:
                try:
                    dt = datetime.strptime(last_upd[:10], "%Y-%m-%d")
                    last_filed = dt.strftime("%Y-%m")
                except ValueError:
                    pass

            business_type = taxpayer.get("ctb")

            risk_flag, risk_explanation = _parse_risk(status, last_filed)

            return GstCheckResult(
                gstin=gstin,
                business_name=trade_name,
                registration_status=status,
                last_return_filed=last_filed,
                state=state_name,
                business_type=business_type,
                risk_flag=risk_flag,
                risk_explanation=risk_explanation,
                data_source="gst_portal",
            )

    except Exception as exc:
        logger.warning("GST portal check failed for %s: %s", gstin, exc)
        risk_flag, risk_explanation = _parse_risk("unknown", None)
        return GstCheckResult(
            gstin=gstin,
            business_name=None,
            registration_status="unknown",
            last_return_filed=None,
            state=state_name,
            business_type=None,
            risk_flag=False,
            risk_explanation=(
                "GST portal is currently unavailable. Please verify GSTIN manually at "
                "https://www.gst.gov.in/searchtaxpayer"
            ),
            data_source="unavailable",
        )
