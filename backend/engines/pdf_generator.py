"""
pdf_generator.py — Mumbai home buying audit report.

10-section report covering everything a buyer needs to know:
    1. Executive Summary + Verdict
    2. What You're Actually Paying (all cost layers)
    3. Financial Reality (EMI, affordability, cash flow)
    4. Stress Test Scenarios
    5. Legal Risk Assessment
    6. Mumbai Location Reality
    7. Long-Term Cost Reality
    8. Behavioral Risk Assessment
    9. AI Roundtable Discussion
    10. Decision Framework + Action Items

Returns PDF as bytes. No AI. No Firebase. Pure ReportLab rendering.
"""

import io
from datetime import datetime
from typing import Optional
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether,
)

# ─── Brand colors ─────────────────────────────────────────────────────────────
BRAND_DARK    = colors.HexColor("#111827")
BRAND_BLUE    = colors.HexColor("#1a56db")
SAFE_GREEN    = colors.HexColor("#059669")
CAUTION_AMBER = colors.HexColor("#d97706")
RISK_RED      = colors.HexColor("#dc2626")
LIGHT_BG      = colors.HexColor("#f9fafb")
BORDER        = colors.HexColor("#d1d5db")
ACCENT        = colors.HexColor("#b45309")
SOFT_BLUE     = colors.HexColor("#eff6ff")


# ─── Style registry ───────────────────────────────────────────────────────────

def _styles():
    s = getSampleStyleSheet()

    s.add(ParagraphStyle(
        "ReportTitle",
        parent=s["Title"],
        fontSize=24, textColor=BRAND_DARK,
        spaceAfter=4, fontName="Helvetica-Bold"
    ))
    s.add(ParagraphStyle(
        "SectionTitle",
        parent=s["Heading1"],
        fontSize=14, textColor=BRAND_BLUE,
        spaceBefore=14, spaceAfter=6,
        fontName="Helvetica-Bold"
    ))
    s.add(ParagraphStyle(
        "SubTitle",
        parent=s["Heading2"],
        fontSize=11, textColor=BRAND_DARK,
        spaceBefore=8, spaceAfter=4,
        fontName="Helvetica-Bold"
    ))
    s.add(ParagraphStyle(
        "Body",
        parent=s["BodyText"],
        fontSize=9, leading=14,
        textColor=BRAND_DARK
    ))
    s.add(ParagraphStyle(
        "BodyBold",
        parent=s["BodyText"],
        fontSize=9, leading=14,
        textColor=BRAND_DARK,
        fontName="Helvetica-Bold"
    ))
    s.add(ParagraphStyle(
        "Small",
        parent=s["BodyText"],
        fontSize=7.5, textColor=colors.gray
    ))
    s.add(ParagraphStyle(
        "VerdictText",
        parent=s["Title"],
        fontSize=28, textColor=BRAND_DARK,
        alignment=1, fontName="Helvetica-Bold"
    ))
    s.add(ParagraphStyle(
        "Disclaimer",
        parent=s["BodyText"],
        fontSize=7, textColor=colors.gray,
        leading=10
    ))
    return s


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _fmt(n) -> str:
    """Format a number as Indian rupees."""
    if n is None:
        return "—"
    n = float(n)
    if n >= 10_000_000:
        return f"₹{n/10_000_000:.2f} Cr"
    if n >= 100_000:
        return f"₹{n/100_000:.1f}L"
    return f"₹{n:,.0f}"


def _pct(n) -> str:
    if n is None:
        return "—"
    return f"{float(n)*100:.1f}%"


def _verdict_color(verdict_str: str) -> colors.Color:
    v = str(verdict_str).lower()
    if "buy_safe" in v or "safe" in v:
        return SAFE_GREEN
    if "caution" in v:
        return CAUTION_AMBER
    return RISK_RED


def _risk_color(score: float) -> colors.Color:
    if score >= 70:
        return SAFE_GREEN
    if score >= 40:
        return CAUTION_AMBER
    return RISK_RED


def _scenario_row(name: str, survivable: bool, buffer: int, shortfall=None) -> list:
    status = "✅ SURVIVES" if survivable else f"❌ BREAKS month {buffer+1}"
    color  = SAFE_GREEN if survivable else RISK_RED
    shortfall_str = _fmt(shortfall) + "/mo shortfall" if shortfall else "—"
    return [name, status, f"{buffer}m buffer", shortfall_str]


def _cost_table(data: list, styles_obj, col_widths=None) -> Table:
    """Build a styled two-column cost table."""
    if col_widths is None:
        col_widths = [110*mm, 50*mm]
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("FONTNAME",    (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE",    (0, 0), (-1, -1), 9),
        ("TEXTCOLOR",   (0, 0), (-1, -1), BRAND_DARK),
        ("ALIGN",       (1, 0), (1, -1), "RIGHT"),
        ("LINEBELOW",   (0, 0), (-1, -1), 0.3, BORDER),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT_BG]),
        ("TOPPADDING",  (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (0, -1), 4),
    ]))
    return t


def _hr(story, thickness=0.5):
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=thickness, color=BORDER))
    story.append(Spacer(1, 4))


# ─── Main generator ───────────────────────────────────────────────────────────

def generate_pdf(
    session_id:           str,
    presentation_output,          # PresentationOutput
    verdict_output,               # VerdictOutput
    mumbai_costs=None,            # MumbaiCostBreakdown dataclass
    collected_data=None,          # CollectedData
) -> bytes:
    """
    Generate the complete 10-section Mumbai home buying audit report.
    Returns PDF as bytes for direct HTTP download.
    """
    output_buf = io.BytesIO()
    doc = SimpleDocTemplate(
        output_buf, pagesize=A4,
        topMargin=18*mm, bottomMargin=18*mm,
        leftMargin=16*mm, rightMargin=16*mm
    )
    S     = _styles()
    story = []
    now   = datetime.now().strftime("%d %B %Y, %I:%M %p")

    # Convenience shorthand
    fr  = presentation_output.pdf_content if presentation_output else None
    vd  = verdict_output
    mc  = mumbai_costs
    cd  = collected_data

    # Safe getters
    def _bb(key, default=None):
        """Get from blackboard/presentation safely."""
        if presentation_output and hasattr(presentation_output, key):
            return getattr(presentation_output, key)
        return default

    def _vd(key, default=None):
        if vd and hasattr(vd, key):
            return getattr(vd, key)
        return default

    def _mc(key, default=0):
        if mc and hasattr(mc, key):
            return getattr(mc, key)
        return default

    def _cd(key, default=None):
        if cd and hasattr(cd, key):
            return getattr(cd, key)
        return default

    # ── Cover / Header ────────────────────────────────────────────────────────
    story.append(Paragraph("NIV AI", S["ReportTitle"]))
    story.append(Paragraph(
        "Mumbai Home Buying Audit Report",
        ParagraphStyle("Sub", parent=S["Body"], fontSize=12, textColor=BRAND_BLUE)
    ))
    story.append(Paragraph(
        f"Session {session_id[:8].upper()} &nbsp;|&nbsp; Generated {now}",
        S["Small"]
    ))
    _hr(story, thickness=2)

    # =========================================================================
    # SECTION 1: EXECUTIVE SUMMARY + VERDICT
    # =========================================================================
    story.append(Paragraph("01 — Executive Summary", S["SectionTitle"]))

    verdict_str   = str(_vd("verdict", "wait")).replace("_", " ").upper()
    verdict_color = _verdict_color(str(_vd("verdict", "")))
    confidence    = _vd("confidence", 0)
    risk_score    = None
    risk_label    = "—"

    if presentation_output and hasattr(presentation_output, "risk_gauge_data"):
        rg = presentation_output.risk_gauge_data
        if rg:
            risk_score = getattr(rg, "score", None)
            risk_label = str(getattr(rg, "label", "—"))

    # Verdict box
    verdict_data = [
        [
            Paragraph(f"<b>VERDICT</b>", S["BodyBold"]),
            Paragraph(f"<b>{verdict_str}</b>",
                ParagraphStyle("VB", parent=S["BodyBold"],
                    textColor=verdict_color, fontSize=14))
        ],
        [
            Paragraph("Confidence", S["Small"]),
            Paragraph(f"{confidence:.0f}%", S["BodyBold"])
        ],
        [
            Paragraph("Risk Score", S["Small"]),
            Paragraph(
                f"{risk_score}/100 — {risk_label}" if risk_score else "—",
                ParagraphStyle("RS", parent=S["BodyBold"],
                    textColor=_risk_color(risk_score or 50))
            )
        ],
    ]
    vt = Table(verdict_data, colWidths=[80*mm, 80*mm])
    vt.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, -1), SOFT_BLUE),
        ("LINEBELOW",   (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING",  (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(vt)
    story.append(Spacer(1, 8))

    # Narrative
    narrative = _vd("final_narrative", "")
    if narrative:
        story.append(Paragraph(narrative, S["Body"]))
    story.append(Spacer(1, 4))

    # Audit summary
    audit_summary = _vd("audit_summary", "")
    if audit_summary:
        story.append(Paragraph(audit_summary, S["Body"]))

    story.append(PageBreak())

    # =========================================================================
    # SECTION 2: WHAT YOU'RE ACTUALLY PAYING
    # =========================================================================
    story.append(Paragraph("02 — What You're Actually Paying", S["SectionTitle"]))
    story.append(Paragraph(
        "Every rupee you need before you get the keys. "
        "The advertised price is never what you actually pay.",
        S["Body"]
    ))
    story.append(Spacer(1, 6))

    if mc:
        # Layer 1: Property cost
        story.append(Paragraph("Property Cost", S["SubTitle"]))
        cost_data = [
            ["Base price (quoted)", _fmt(_mc("base_price"))],
            [f"Floor rise charges (floor {_cd('floor_number', '—')})", _fmt(_mc("floor_rise_charges"))],
            [f"PLC ({_cd('facing', '—')} facing)", _fmt(_mc("plc_charges"))],
            ["Parking", _fmt(_mc("parking_cost"))],
            ["", ""],
            [Paragraph("<b>Advertised Total</b>", S["BodyBold"]),
             Paragraph(f"<b>{_fmt(_mc('advertised_total'))}</b>", S["BodyBold"])],
        ]
        story.append(_cost_table(cost_data, S))
        story.append(Spacer(1, 8))

        # Layer 2: Government charges
        story.append(Paragraph("Government Charges (Non-Negotiable)", S["SubTitle"]))
        govt_data = [
            [f"Stamp duty ({_mc('stamp_duty')/_mc('advertised_total', 1)*100:.0f}%)", _fmt(_mc("stamp_duty"))],
            ["Metro cess (1% — all Mumbai properties)", _fmt(_mc("metro_cess"))],
            ["Registration fee (capped ₹30,000)", _fmt(_mc("registration_fee"))],
            [Paragraph("<b>Total Govt Charges</b>", S["BodyBold"]),
             Paragraph(f"<b>{_fmt(_mc('total_govt_charges'))}</b>", S["BodyBold"])],
        ]
        story.append(_cost_table(govt_data, S))
        story.append(Spacer(1, 8))

        # Layer 3+5: Builder and legal
        story.append(Paragraph("Builder / Society Charges", S["SubTitle"]))
        builder_data = [
            ["GST (5% under-construction, 0% ready-to-move)", _fmt(_mc("gst"))],
            ["Maintenance deposit (24 months upfront)", _fmt(_mc("maintenance_deposit"))],
            ["Society formation charges", _fmt(_mc("society_formation_charges"))],
            ["Corpus fund", _fmt(_mc("corpus_fund"))],
            ["Clubhouse / amenities fee", _fmt(_mc("clubhouse_fee"))],
            [Paragraph("<b>Total Builder Charges</b>", S["BodyBold"]),
             Paragraph(f"<b>{_fmt(_mc('total_builder_charges'))}</b>", S["BodyBold"])],
        ]
        story.append(_cost_table(builder_data, S))
        story.append(Spacer(1, 8))

        story.append(Paragraph("Legal & Loan Costs", S["SubTitle"]))
        legal_data = [
            ["Lawyer fees + title verification", _fmt(_mc("lawyer_fees"))],
            ["Agreement drafting", _fmt(_mc("agreement_drafting"))],
            ["Due diligence (disputes, approvals)", _fmt(_mc("due_diligence_fee"))],
            ["Loan processing fee (0.75%)", _fmt(_mc("loan_processing_fee"))],
            ["Loan insurance (optional)", _fmt(_mc("loan_insurance_estimate"))],
            [Paragraph("<b>Total Legal + Loan Costs</b>", S["BodyBold"]),
             Paragraph(f"<b>{_fmt(_mc('total_legal_costs') + _mc('total_loan_costs'))}</b>",
                       S["BodyBold"])],
        ]
        story.append(_cost_table(legal_data, S))
        story.append(Spacer(1, 10))

        # Grand total
        total_data = [
            [Paragraph("<b>TRUE COST TO GET THE KEYS</b>", S["BodyBold"]),
             Paragraph(f"<b>{_fmt(_mc('true_total_acquisition_cost'))}</b>",
                ParagraphStyle("GT", parent=S["BodyBold"], textColor=RISK_RED, fontSize=11))],
            ["+ Interior fit-out estimate", _fmt(_mc("interior_estimate"))],
            [Paragraph("<b>TOTAL WITH INTERIORS</b>", S["BodyBold"]),
             Paragraph(f"<b>{_fmt(_mc('true_total_with_interiors'))}</b>",
                ParagraphStyle("GT2", parent=S["BodyBold"], textColor=RISK_RED, fontSize=11))],
            ["", ""],
            [Paragraph(
                f"<b>Hidden cost above advertised: "
                f"{_fmt(_mc('hidden_cost_above_advertised'))} "
                f"({_mc('hidden_cost_percentage'):.1f}% more)</b>",
                ParagraphStyle("Warn", parent=S["BodyBold"], textColor=CAUTION_AMBER)),
             ""],
        ]
        gt = Table(total_data, colWidths=[110*mm, 50*mm])
        gt.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), SOFT_BLUE),
            ("LINEBELOW",     (0, 0), (-1, -1), 0.5, BORDER),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("ALIGN",         (1, 0), (1, -1), "RIGHT"),
        ]))
        story.append(gt)

        story.append(Spacer(1, 6))
        story.append(Paragraph(_mc("cost_breakdown_text", ""), S["Body"]))

    story.append(PageBreak())

    # =========================================================================
    # SECTION 3: FINANCIAL REALITY
    # =========================================================================
    story.append(Paragraph("03 — Your Financial Reality", S["SectionTitle"]))

    fr_data = None
    if presentation_output:
        # Try to get financial reality from presentation context
        scenario_data = getattr(presentation_output, "affordability_bar_data", None)
        rg_data       = getattr(presentation_output, "risk_gauge_data", None)

    # Pull from pdf_content if available
    pdf_c = getattr(presentation_output, "pdf_content", None)
    cash_flow_content = ""
    if pdf_c:
        cf_section = getattr(pdf_c, "cash_flow_section", None)
        if cf_section:
            cash_flow_content = getattr(cf_section, "content", "")

    story.append(Paragraph(
        getattr(presentation_output, "formatted_risk_summary", "") or
        "Financial analysis based on your inputs.",
        S["Body"]
    ))
    story.append(Spacer(1, 6))

    if cash_flow_content:
        story.append(Paragraph(cash_flow_content, S["Body"]))

    # Affordability bar
    aff = getattr(presentation_output, "affordability_bar_data", None)
    if aff:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Price Comparison", S["SubTitle"]))
        price_cmp = [
            ["Property you're considering", _fmt(getattr(aff, "asked_price", 0))],
            ["Safe price (EMI = 35% of income)", _fmt(getattr(aff, "safe_price", 0))],
            ["Maximum price (EMI = 50% of income)", _fmt(getattr(aff, "maximum_price", 0))],
        ]
        story.append(_cost_table(price_cmp, S))

    story.append(PageBreak())

    # =========================================================================
    # SECTION 4: STRESS TEST SCENARIOS
    # =========================================================================
    story.append(Paragraph("04 — Stress Test Scenarios", S["SectionTitle"]))
    story.append(Paragraph(
        "We simulated 5 financial shocks over 24 months. "
        "This tells you which risks would actually break your finances.",
        S["Body"]
    ))
    story.append(Spacer(1, 6))

    scenario_explanations = getattr(presentation_output, "scenario_explanations", {}) or {}
    scenario_cmp          = getattr(presentation_output, "scenario_comparison_data", None)

    if scenario_cmp:
        names      = getattr(scenario_cmp, "scenario_names", [])
        buffers    = getattr(scenario_cmp, "buffer_months", [])
        survivable = getattr(scenario_cmp, "survivable", [])

        scenario_table_data = [
            [
                Paragraph("<b>Scenario</b>", S["BodyBold"]),
                Paragraph("<b>Result</b>", S["BodyBold"]),
                Paragraph("<b>Buffer</b>", S["BodyBold"]),
                Paragraph("<b>Plain English</b>", S["BodyBold"]),
            ]
        ]
        scenario_key_map = {
            "Base Case":      "base_case",
            "Income -30%":    "income_drop_30pct",
            "Job Loss 6mo":   "job_loss_6_months",
            "Rate +2%":       "interest_rate_hike_2pct",
            "Emergency ₹5L":  "emergency_expense_5L",
        }
        for i, name in enumerate(names):
            surv   = survivable[i] if i < len(survivable) else True
            buf    = buffers[i]    if i < len(buffers)    else 0
            status = "✅ SURVIVES" if surv else f"❌ BREAKS M{buf+1}"
            expl   = scenario_explanations.get(scenario_key_map.get(name, ""), "")
            scenario_table_data.append([
                name, status, f"{buf}m",
                Paragraph(expl[:120] if expl else "—", S["Small"])
            ])

        st = Table(scenario_table_data, colWidths=[38*mm, 28*mm, 18*mm, 76*mm])
        st.setStyle(TableStyle([
            ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8),
            ("BACKGROUND",    (0, 0), (-1, 0),  BRAND_BLUE),
            ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, LIGHT_BG]),
            ("LINEBELOW",     (0, 0), (-1, -1), 0.3, BORDER),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 4),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(st)

    story.append(PageBreak())

    # =========================================================================
    # SECTION 5: LEGAL RISK ASSESSMENT
    # =========================================================================
    story.append(Paragraph("05 — Legal Risk Assessment", S["SectionTitle"]))
    story.append(Paragraph(
        "Mumbai has a high rate of disputed titles, redevelopment notices, "
        "and incomplete approvals. Never skip this.",
        S["Body"]
    ))
    story.append(Spacer(1, 6))

    legal_audit = _vd("legal_audit", "")
    if legal_audit:
        for para in legal_audit.split("\n\n"):
            p = para.strip()
            if p:
                story.append(Paragraph(p.replace("\n", "<br/>"), S["Body"]))
                story.append(Spacer(1, 3))
    else:
        # Checklist fallback
        checklist = [
            ["Item", "Status", "Notes"],
            ["RERA Registration (MahaRERA)", "⚠ Verify", "Check maharera.mahaonline.gov.in"],
            ["Occupancy Certificate (OC)", "⚠ Verify", "Must be obtained for ready-to-move"],
            ["Commencement Certificate (CC)", "⚠ Verify", "Required before construction begins"],
            ["Clear title (last 30 years)", "⚠ Verify", "No disputes, no encumbrances"],
            ["Encumbrance Certificate", "⚠ Verify", "Confirm no active mortgage on property"],
            ["Land use approval", "⚠ Verify", "Residential zone confirmed by BMC"],
            ["Redevelopment notice", "⚠ Verify", "Check if building has any SRA notice"],
        ]
        ct = Table(checklist, colWidths=[55*mm, 30*mm, 75*mm])
        ct.setStyle(TableStyle([
            ("FONTNAME",    (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("FONTSIZE",    (0, 0), (-1, -1), 8),
            ("BACKGROUND",  (0, 0), (-1, 0),  BRAND_BLUE),
            ("TEXTCOLOR",   (0, 0), (-1, 0),  colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
            ("LINEBELOW",   (0, 0), (-1, -1), 0.3, BORDER),
            ("TOPPADDING",  (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(ct)

    # Risk flags from mumbai_costs
    if mc:
        risk_flags = _mc("risk_flags", [])
        if risk_flags:
            story.append(Spacer(1, 8))
            story.append(Paragraph("Mumbai-Specific Risk Flags", S["SubTitle"]))
            for flag in risk_flags:
                story.append(Paragraph(f"⚠  {flag}", S["Body"]))
                story.append(Spacer(1, 2))

    story.append(PageBreak())

    # =========================================================================
    # SECTION 6: MUMBAI LOCATION REALITY
    # =========================================================================
    story.append(Paragraph("06 — Mumbai Location Reality", S["SectionTitle"]))

    if mc:
        locality = _mc("locality", "—")
        ppsf     = _mc("price_per_sqft_actual", 0)
        mkt_low  = _mc("market_price_per_sqft_low", 0)
        mkt_high = _mc("market_price_per_sqft_high", 0)
        vs_mkt   = _mc("price_vs_market", "unknown")
        premium  = _mc("price_premium_pct", 0)
        rent     = _mc("estimated_monthly_rent", 0)
        yield_pct = _mc("estimated_rental_yield_pct", 2.5)

        loc_data = [
            ["Locality", str(locality).title()],
            ["Your price per sqft (carpet)", f"₹{ppsf:,.0f}"],
            ["Market range in this area",
             f"₹{mkt_low:,} – ₹{mkt_high:,}/sqft" if mkt_low else "Unknown locality"],
            ["Price vs market",
             f"{vs_mkt.upper()} ({premium:+.1f}%)"],
            ["Estimated monthly rent", _fmt(rent)],
            ["Estimated rental yield", f"{yield_pct:.1f}% per year"],
        ]
        story.append(_cost_table(loc_data, S))
        story.append(Spacer(1, 8))

        story.append(Paragraph(
            "<b>Mumbai Real Talk:</b> You're paying a premium for location, not space. "
            "Carpet area is what matters — super built-up area can be 25-40% larger. "
            f"At ₹{ppsf:,.0f}/sqft carpet, compare this against similar projects in "
            f"{str(locality).title()} before signing.",
            S["Body"]
        ))
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            f"Rental yield at {yield_pct:.1f}% means this is primarily a "
            "long-term asset and lifestyle decision — not an income-generating investment. "
            "Factor in the locked-up capital opportunity cost.",
            S["Body"]
        ))

    story.append(PageBreak())

    # =========================================================================
    # SECTION 7: LONG-TERM COST REALITY
    # =========================================================================
    story.append(Paragraph("07 — Long-Term Cost Reality", S["SectionTitle"]))
    story.append(Paragraph(
        "These costs don't show up at purchase but accumulate over your ownership.",
        S["Body"]
    ))
    story.append(Spacer(1, 6))

    if mc:
        maint_mo  = _mc("monthly_maintenance", 0)
        tax_yr    = _mc("annual_property_tax", 0)
        interior  = _mc("interior_estimate", 0)
        ongoing   = _mc("total_first_year_ongoing", 0)

        ongoing_data = [
            ["Monthly maintenance (society)", f"{_fmt(maint_mo)}/month"],
            ["Annual property tax (BMC)", f"{_fmt(tax_yr)}/year"],
            ["Interior fit-out (one-time estimate)", _fmt(interior)],
            ["Total first year ongoing costs", _fmt(ongoing + interior)],
            ["10-year total ongoing (excl. inflation)", _fmt((maint_mo * 12 + tax_yr) * 10)],
        ]
        story.append(_cost_table(ongoing_data, S))
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "Maintenance charges in Mumbai typically increase 5-10% annually. "
            "Budget for repairs of ₹2-5L every 5-7 years for a standard apartment.",
            S["Body"]
        ))

    story.append(PageBreak())

    # =========================================================================
    # SECTION 8: BEHAVIORAL RISK ASSESSMENT
    # =========================================================================
    story.append(Paragraph("08 — Behavioral Risk Assessment", S["SectionTitle"]))
    story.append(Paragraph(
        "Over 40% of bad property decisions are driven by psychological biases, "
        "not bad math. Here's what we detected in your conversation.",
        S["Body"]
    ))
    story.append(Spacer(1, 6))

    behavioral_audit = _vd("behavioral_audit", "")
    pdf_behavioral   = ""
    if pdf_c:
        bs = getattr(pdf_c, "behavioral_section", None)
        if bs:
            pdf_behavioral = getattr(bs, "content", "")

    behavioral_text = behavioral_audit or pdf_behavioral or \
        getattr(presentation_output, "behavioral_summary", "") or \
        "Behavioral analysis not available."

    for para in behavioral_text.split("\n\n"):
        p = para.strip()
        if p:
            story.append(Paragraph(p.replace("\n", "<br/>"), S["Body"]))
            story.append(Spacer(1, 3))

    # Warning cards
    warning_cards = getattr(presentation_output, "warning_cards", []) or []
    if warning_cards:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Key Warnings", S["SubTitle"]))
        for card in warning_cards[:5]:
            title    = getattr(card, "title", "")
            desc     = getattr(card, "description", "")
            severity = getattr(card, "severity", "medium")
            c        = RISK_RED if severity == "high" else (
                CAUTION_AMBER if severity == "medium" else SAFE_GREEN
            )
            story.append(Paragraph(
                f"<b>{title}</b>",
                ParagraphStyle("WarnTitle", parent=S["BodyBold"], textColor=c)
            ))
            story.append(Paragraph(desc, S["Body"]))
            story.append(Spacer(1, 3))

    story.append(PageBreak())

    # =========================================================================
    # SECTION 9: AI ROUNDTABLE DISCUSSION
    # =========================================================================
    story.append(Paragraph("09 — AI Expert Roundtable", S["SectionTitle"]))
    story.append(Paragraph(
        "Three AI specialists debated your specific financial situation. "
        "Marcus is the financial analyst. Zara is the risk strategist. "
        "Soren is the behavioral economist.",
        S["Body"]
    ))
    story.append(Spacer(1, 6))

    # Financial audit
    fin_audit = _vd("financial_audit", "")
    if fin_audit:
        story.append(Paragraph("Marcus — Financial Analysis", S["SubTitle"]))
        for para in fin_audit.split("\n\n")[:4]:
            p = para.strip()
            if p:
                story.append(Paragraph(p.replace("\n", "<br/>"), S["Body"]))
                story.append(Spacer(1, 3))

    # Risk audit
    risk_audit = _vd("risk_audit", "")
    if risk_audit:
        story.append(Paragraph("Zara — Risk Assessment", S["SubTitle"]))
        for para in risk_audit.split("\n\n")[:4]:
            p = para.strip()
            if p:
                story.append(Paragraph(p.replace("\n", "<br/>"), S["Body"]))
                story.append(Spacer(1, 3))

    # Banking + tax audit
    bank_audit = _vd("banking_audit", "")
    tax_audit  = _vd("tax_audit", "")
    if bank_audit or tax_audit:
        story.append(Paragraph("Soren — Behavioral + Structural Observations", S["SubTitle"]))
        combined = (bank_audit + "\n\n" + tax_audit).strip()
        for para in combined.split("\n\n")[:3]:
            p = para.strip()
            if p:
                story.append(Paragraph(p.replace("\n", "<br/>"), S["Body"]))
                story.append(Spacer(1, 3))

    story.append(PageBreak())

    # =========================================================================
    # SECTION 10: DECISION FRAMEWORK + ACTION ITEMS
    # =========================================================================
    story.append(Paragraph("10 — Decision Framework & Action Items", S["SectionTitle"]))

    # Three-layer decision framework
    story.append(Paragraph("The Three-Layer Check", S["SubTitle"]))

    # Get affordability status from risk gauge
    risk_s = risk_score or 50
    afford_pass  = risk_s >= 60
    legal_pass   = not (_mc("flood_zone_risk", False) or _mc("redevelopment_risk", False))

    framework_data = [
        [
            Paragraph("<b>Layer</b>", S["BodyBold"]),
            Paragraph("<b>Check</b>", S["BodyBold"]),
            Paragraph("<b>Status</b>", S["BodyBold"]),
        ],
        [
            "1. Affordability",
            "EMI ≤ 40% of income + survives stress tests",
            Paragraph("✅ PASS" if afford_pass else "❌ REVIEW",
                ParagraphStyle("P", parent=S["BodyBold"],
                    textColor=SAFE_GREEN if afford_pass else RISK_RED))
        ],
        [
            "2. Legality",
            "Clean title + RERA registered + OC obtained",
            Paragraph("⚠ VERIFY", ParagraphStyle("L", parent=S["BodyBold"], textColor=CAUTION_AMBER))
        ],
        [
            "3. Livability",
            "Commute, maintenance, society quality",
            Paragraph("✅ ASSESS" if not legal_pass else "✅ CHECK",
                ParagraphStyle("LV", parent=S["BodyBold"], textColor=CAUTION_AMBER))
        ],
    ]
    ft = Table(framework_data, colWidths=[40*mm, 85*mm, 35*mm])
    ft.setStyle(TableStyle([
        ("FONTNAME",    (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, -1), 9),
        ("BACKGROUND",  (0, 0), (-1, 0),  BRAND_BLUE),
        ("TEXTCOLOR",   (0, 0), (-1, 0),  colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
        ("LINEBELOW",   (0, 0), (-1, -1), 0.3, BORDER),
        ("TOPPADDING",  (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(ft)
    story.append(Spacer(1, 10))

    # Action items
    story.append(Paragraph("Recommended Actions Before Signing", S["SubTitle"]))
    suggested_actions = _vd("suggested_actions", []) or []
    if suggested_actions:
        for i, action in enumerate(suggested_actions, 1):
            story.append(Paragraph(f"{i}. {action}", S["Body"]))
            story.append(Spacer(1, 2))
    else:
        # Default actions
        default_actions = [
            "Verify RERA registration on maharera.mahaonline.gov.in using the project name or RERA number.",
            "Obtain an Encumbrance Certificate for the last 30 years from the Sub-Registrar office.",
            "Confirm the Occupancy Certificate (OC) has been issued — do not buy without OC.",
            "Have a lawyer review the sale agreement specifically for penalty clauses and force majeure terms.",
            "Negotiate the parking cost separately — it is often inflated.",
            "Confirm carpet area measurement independently — have it verified by a civil engineer.",
            "Keep at least 6 months of EMI as emergency buffer before signing.",
        ]
        for i, action in enumerate(default_actions, 1):
            story.append(Paragraph(f"{i}. {action}", S["Body"]))
            story.append(Spacer(1, 2))

    # Unresolved conflicts
    conflicts = _vd("unresolved_conflicts", []) or []
    if conflicts:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Open Questions Before You Proceed", S["SubTitle"]))
        for c in conflicts:
            story.append(Paragraph(f"• {c}", S["Body"]))
            story.append(Spacer(1, 2))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 16))
    _hr(story)
    story.append(Paragraph(
        "This report is for informational purposes only and does not constitute financial, "
        "legal, or investment advice. All calculations are based on inputs provided by the "
        "user and standard Mumbai market estimates. Consult a SEBI-registered investment "
        "advisor, property lawyer, and certified financial planner before making any "
        "property purchase decision.",
        S["Disclaimer"]
    ))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Powered by NIV AI — aligned with UN SDG 1 (No Poverty) and SDG 10 (Reduced Inequalities). "
        f"Report ID: {session_id[:8].upper()} | {now}",
        S["Disclaimer"]
    ))

    # ── Build ─────────────────────────────────────────────────────────────────
    doc.build(story)
    pdf_bytes = output_buf.getvalue()
    output_buf.close()
    return pdf_bytes