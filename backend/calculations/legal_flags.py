"""
Legal status flags for NIV AI property analysis.

Deterministic rules for flagging Occupancy Certificate (OC) and
Completion Certificate (CC) status based on property metadata.
These documents are required for:
  - Legal occupation (living without OC is illegal)
  - Water/electricity at domestic rates (commercial rates without OC)
  - Property registration as home address
  - Future resale without complications

No LLM — pure rule-based risk assessment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class OcCcStatus:
    """Assessment of Occupancy Certificate and Completion Certificate status."""

    oc_status: str  # "likely_obtained" | "likely_pending" | "at_risk" | "unknown"
    cc_status: str  # same enum
    risk_level: str  # "low" | "medium" | "high" | "critical"
    risk_flags: list = field(default_factory=list)
    legal_implications: list = field(default_factory=list)
    recommended_actions: list = field(default_factory=list)
    overall_note: str = ""


_LEGAL_IMPLICATIONS = [
    "Living without OC constitutes unauthorized occupation and is legally invalid in Maharashtra.",
    "Without OC, water and electricity are billed at commercial rates (2-5x higher).",
    "Cannot register the property as a primary residential address without OC.",
    "Resale of property without OC is difficult and may attract legal liability.",
]


def _parse_possession_date(possession_date: str) -> Optional[datetime]:
    """
    Parses possession date from MM/YYYY or YYYY-MM-DD format.

    Args:
        possession_date: Date string.

    Returns:
        datetime object or None if unparseable.
    """
    if not possession_date or not possession_date.strip():
        return None
    for fmt in ("%m/%Y", "%Y-%m-%d", "%m-%Y", "%Y/%m"):
        try:
            return datetime.strptime(possession_date.strip(), fmt)
        except ValueError:
            pass
    return None


def assess_oc_cc_status(
    is_ready_to_move: bool,
    possession_date: str,
    is_rera_registered: Optional[bool],
    builder_name: str,
    rera_data: Optional[dict] = None,
) -> OcCcStatus:
    """
    Assesses OC/CC risk based on available property metadata.

    Rules (in order of severity):
      CRITICAL:
        - is_ready_to_move=True but possession_date in future
        - is_ready_to_move=True and is_rera_registered=False

      HIGH:
        - is_ready_to_move=False with past possession_date
        - rera_data registration_status=lapsed and is_ready_to_move=True

      MEDIUM:
        - is_ready_to_move=True and is_rera_registered=None
        - Under construction with no possession date

      LOW (pass):
        - is_ready_to_move=True and is_rera_registered=True

    Args:
        is_ready_to_move: Boolean from user input.
        possession_date: String date (MM/YYYY format) or empty.
        is_rera_registered: Boolean or None from user input.
        builder_name: Builder name for context.
        rera_data: Optional RERA check result dict.

    Returns:
        OcCcStatus with risk assessment.
    """
    risk_flags: list[str] = []
    risk_level = "low"
    oc_status = "unknown"
    cc_status = "unknown"
    recommended_actions: list[str] = [
        "Request copies of OC and CC from the builder before signing any agreement.",
        "Verify OC status with the local Municipal Corporation (BMC for Mumbai).",
        "Have a property lawyer review all documents before payment.",
    ]

    poss_dt = _parse_possession_date(possession_date)
    now = datetime.now()
    rera_lapsed = (
        rera_data.get("registration_status") == "lapsed"
        if rera_data
        else False
    )

    if is_ready_to_move:
        # CRITICAL RULES
        if poss_dt and poss_dt > now:
            risk_level = "critical"
            risk_flags.append(
                f"Builder claims ready-to-move but possession date ({possession_date}) is in the future. "
                "This inconsistency suggests OC may not have been obtained."
            )
            oc_status = "at_risk"
            cc_status = "at_risk"

        if is_rera_registered is False:
            risk_level = "critical"
            risk_flags.append(
                "Property is claimed as ready-to-move but is not RERA registered. "
                "Under Maharashtra RERA, this is non-compliant and OC status is unverifiable."
            )
            oc_status = "at_risk"
            cc_status = "at_risk"

        # HIGH RULES
        if rera_lapsed and risk_level != "critical":
            risk_level = "high"
            risk_flags.append(
                "Builder's RERA registration has lapsed while claiming ready-to-move status. "
                "OC and CC status cannot be independently verified."
            )
            oc_status = "at_risk"
            cc_status = "likely_pending"

        # MEDIUM RULES
        if is_rera_registered is None and risk_level == "low":
            risk_level = "medium"
            risk_flags.append(
                "RERA status is unknown for this ready-to-move property. "
                "Verify OC and CC documents before registration."
            )
            oc_status = "unknown"
            cc_status = "unknown"

        # LOW (PASS)
        if is_rera_registered is True and risk_level == "low":
            oc_status = "likely_obtained"
            cc_status = "likely_obtained"

    else:
        # Under construction
        if poss_dt and poss_dt < now:
            risk_level = "high"
            risk_flags.append(
                f"Promised possession date ({possession_date}) has already passed but property is "
                "under construction. Significant delay in OC/CC is likely."
            )
            oc_status = "at_risk"
            cc_status = "likely_pending"
        elif not poss_dt:
            risk_level = "medium"
            risk_flags.append(
                "No possession date provided for under-construction property. "
                "OC/CC timeline is unclear."
            )
            oc_status = "likely_pending"
            cc_status = "likely_pending"
        else:
            oc_status = "likely_pending"
            cc_status = "likely_pending"
            if risk_level == "low":
                risk_level = "medium"
            if not risk_flags:
                risk_flags.append(
                    f"Under-construction property — OC/CC will only be issued after completion "
                    f"(expected {possession_date})."
                )

    # Build overall note
    notes = {
        "critical": "CRITICAL: OC/CC status raises serious legal concerns. Do not proceed without legal clearance.",
        "high": "HIGH RISK: OC/CC status requires immediate verification before purchase.",
        "medium": "CAUTION: OC/CC status should be confirmed before signing any agreement.",
        "low": "OC/CC status appears satisfactory based on available data. Verify documents before closing.",
    }
    overall_note = notes.get(risk_level, "OC/CC status unknown — verify with builder.")

    return OcCcStatus(
        oc_status=oc_status,
        cc_status=cc_status,
        risk_level=risk_level,
        risk_flags=risk_flags,
        legal_implications=_LEGAL_IMPLICATIONS,
        recommended_actions=recommended_actions,
        overall_note=overall_note,
    )
