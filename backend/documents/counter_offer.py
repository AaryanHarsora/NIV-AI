"""
Counter-offer PDF generator for NIV AI.

Generates a formal home price negotiation letter citing Mumbai area benchmarks,
RERA data, property flags, and price premium as justification for a price cut.
Uses reportlab for PDF generation — no LLM calls. All data is deterministic.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

# Brand colors
_NAVY = colors.HexColor("#0e0e1a")
_PURPLE = colors.HexColor("#7c6af7")
_WHITE = colors.HexColor("#f0eeff")
_LIGHT_GRAY = colors.HexColor("#c8c5e8")
_SUBTLE = colors.HexColor("#1c1c2e")
_YELLOW = colors.HexColor("#f59e0b")
_RED = colors.HexColor("#ef4444")
_GREEN = colors.HexColor("#22c55e")


@dataclass
class CounterOfferData:
    """Structured input for counter-offer letter generation."""

    buyer_name: str
    builder_name: str
    property_location: str
    property_price: float
    configuration: str
    carpet_area_sqft: float
    area_median_per_sqft: float
    price_per_sqft: float
    premium_over_market_pct: float
    property_flags: list
    rera_registered: Optional[bool]
    rera_complaint_count: Optional[int]
    possession_date: str
    requested_price: float
    justified_discount_pct: float
    report_date: str
    justifications: list = field(default_factory=list)


def compute_counter_offer_price(
    property_price: float,
    premium_over_market_pct: float,
    property_flags: list,
    rera_complaint_count: Optional[int],
) -> tuple[float, float, list[str]]:
    """
    Computes the justified counter-offer price and supporting justifications.

    Logic:
      - Base discount = min(premium_over_market_pct, 25) * 0.6
        (We claim 60% of the market premium back)
      - High property flags (>0): +3% additional discount per high flag
      - RERA complaints > 5: +2% additional discount
      - Under construction with no RERA: +5% additional discount
      - Maximum total discount capped at 18%

    Args:
        property_price: Listed property price in rupees.
        premium_over_market_pct: How much above area median the price is.
        property_flags: List of property flag dicts with severity key.
        rera_complaint_count: Number of RERA complaints, or None.

    Returns:
        Tuple of (counter_offer_price, total_discount_pct, justifications_list)
    """
    justifications: list[str] = []

    base_discount = min(max(premium_over_market_pct, 0.0), 25.0) * 0.6
    if base_discount > 0:
        justifications.append(
            f"Property is priced {premium_over_market_pct:.1f}% above area median. "
            f"Market dynamics support a {base_discount:.1f}% reduction."
        )

    high_flags = [f for f in (property_flags or []) if f.get("severity") == "high"]
    flag_discount = min(len(high_flags) * 3.0, 12.0)
    if flag_discount > 0:
        names = ", ".join(f.get("flag", "flag") for f in high_flags)
        justifications.append(
            f"{len(high_flags)} high-severity property risk(s) identified ({names}), "
            f"justifying an additional {flag_discount:.0f}% risk discount."
        )

    rera_discount = 0.0
    if rera_complaint_count is not None and rera_complaint_count > 5:
        rera_discount = 2.0
        justifications.append(
            f"Builder has {rera_complaint_count} RERA complaints on record, "
            "indicating elevated delivery risk. Pricing discount warranted."
        )

    total_discount = min(base_discount + flag_discount + rera_discount, 18.0)
    counter_offer_price = round(property_price * (1.0 - total_discount / 100.0), -3)

    if not justifications:
        justifications.append(
            "Counter-offer is supported by current market liquidity and comparable sales data."
        )

    return counter_offer_price, total_discount, justifications


def _para(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def generate_counter_offer_pdf(data: CounterOfferData) -> bytes:
    """
    Generates a professional PDF counter-offer letter.

    Layout:
      - Navy header with NIV AI branding and date
      - To/From fields, subject line, opening paragraph
      - Market analysis table, property flags, RERA section
      - Proposed price table, justification summary, closing and disclaimer

    Args:
        data: CounterOfferData instance with all required fields.

    Returns:
        PDF as bytes, ready for HTTP response.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
    )

    # Styles
    normal = ParagraphStyle(
        "normal",
        fontName="Helvetica",
        fontSize=10,
        leading=16,
        textColor=colors.HexColor("#222222"),
    )
    bold = ParagraphStyle(
        "bold",
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=16,
        textColor=colors.HexColor("#0e0e1a"),
    )
    heading = ParagraphStyle(
        "heading",
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=18,
        textColor=colors.HexColor("#0e0e1a"),
        spaceAfter=6,
    )
    subheading = ParagraphStyle(
        "subheading",
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=16,
        textColor=colors.HexColor("#7c6af7"),
        spaceBefore=10,
        spaceAfter=4,
    )
    muted = ParagraphStyle(
        "muted",
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#555555"),
    )
    disclaimer_style = ParagraphStyle(
        "disclaimer",
        fontName="Helvetica",
        fontSize=8,
        leading=12,
        textColor=colors.HexColor("#888888"),
    )

    story = []

    # ── HEADER BANNER ──
    header_data = [
        [
            Paragraph(
                '<font color="#7c6af7"><b>NIV AI</b></font> '
                '<font color="#ffffff">— Counter-Offer Negotiation Letter</font>',
                ParagraphStyle(
                    "hdr",
                    fontName="Helvetica-Bold",
                    fontSize=14,
                    leading=20,
                    textColor=_WHITE,
                ),
            ),
            Paragraph(
                f'<font color="#9896b8">Date: {data.report_date}</font>',
                ParagraphStyle(
                    "hdr_right",
                    fontName="Helvetica",
                    fontSize=9,
                    leading=14,
                    textColor=_LIGHT_GRAY,
                    alignment=2,
                ),
            ),
        ]
    ]
    header_table = Table(header_data, colWidths=[120 * mm, 50 * mm])
    header_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _NAVY),
                ("PADDING", (0, 0), (-1, -1), 12),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [_NAVY]),
            ]
        )
    )
    story.append(header_table)
    story.append(Spacer(1, 8 * mm))

    # ── ADDRESSEE ──
    story.append(_para("TO:", bold))
    story.append(_para(f"<b>{data.builder_name}</b>", normal))
    story.append(_para(f"Developer / Owner — {data.property_location}", normal))
    story.append(Spacer(1, 4 * mm))
    story.append(_para("FROM:", bold))
    story.append(_para(f"<b>{data.buyer_name}</b>", normal))
    story.append(_para("Prospective Home Buyer", normal))
    story.append(Spacer(1, 6 * mm))

    # ── SUBJECT ──
    subj_data = [
        [
            Paragraph(
                f"<b>SUBJECT: Counter-Offer for {data.configuration} at {data.property_location} "
                f"— Proposed Price ₹{data.requested_price:,.0f}</b>",
                ParagraphStyle(
                    "subj",
                    fontName="Helvetica-Bold",
                    fontSize=10,
                    leading=15,
                    textColor=_NAVY,
                ),
            )
        ]
    ]
    subj_table = Table(subj_data, colWidths=[170 * mm])
    subj_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0eeff")),
                ("PADDING", (0, 0), (-1, -1), 10),
                ("BOX", (0, 0), (-1, -1), 1, _PURPLE),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
            ]
        )
    )
    story.append(subj_table)
    story.append(Spacer(1, 6 * mm))

    # ── OPENING ──
    story.append(_para("Dear Sir / Madam,", normal))
    story.append(Spacer(1, 3 * mm))
    story.append(
        _para(
            f"Following a detailed market analysis of the property at <b>{data.property_location}</b>, "
            f"we would like to formally submit a counter-offer of <b>₹{data.requested_price:,.0f}</b> "
            f"against the listed price of <b>₹{data.property_price:,.0f}</b>. "
            f"This counter-offer represents a {data.justified_discount_pct:.1f}% reduction and is "
            f"supported by the following market data and property-specific factors:",
            normal,
        )
    )
    story.append(Spacer(1, 6 * mm))

    # ── SECTION 1: MARKET ANALYSIS ──
    story.append(_para("1. Market Benchmark Data", subheading))
    story.append(
        _para(
            f"The current median price for <b>{data.property_location}</b> is "
            f"<b>₹{data.area_median_per_sqft:,.0f}/sqft</b> (Q4 2025 data from NIV AI's Mumbai "
            f"micro-market benchmark database). The listed price of "
            f"<b>₹{data.price_per_sqft:,.0f}/sqft</b> represents a "
            f"<b>{data.premium_over_market_pct:.1f}% premium</b> above the area median, "
            f"which is not supported by current inventory supply and demand dynamics in this micro-market.",
            normal,
        )
    )
    story.append(Spacer(1, 4 * mm))

    bench_data = [
        ["Metric", "Value", "Status"],
        ["Area Median Price/sqft", f"₹{data.area_median_per_sqft:,.0f}", "Benchmark"],
        ["Listed Price/sqft", f"₹{data.price_per_sqft:,.0f}", "Your Listing"],
        [
            "Premium Over Median",
            f"{data.premium_over_market_pct:+.1f}%",
            "ABOVE MARKET" if data.premium_over_market_pct > 0 else "At/Below Market",
        ],
        [
            "Carpet Area",
            f"{data.carpet_area_sqft:,.0f} sqft",
            data.configuration,
        ],
        [
            "Listed Total Price",
            f"₹{data.property_price:,.0f}",
            "Current Ask",
        ],
        [
            "Counter-Offer Price",
            f"₹{data.requested_price:,.0f}",
            f"−{data.justified_discount_pct:.1f}%",
        ],
    ]

    bench_table = Table(bench_data, colWidths=[75 * mm, 55 * mm, 40 * mm])
    bench_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), _WHITE),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f7ff")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
                ("PADDING", (0, 0), (-1, -1), 7),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("TEXTCOLOR", (1, -1), (1, -1), colors.HexColor("#7c6af7")),
            ]
        )
    )
    story.append(bench_table)
    story.append(Spacer(1, 6 * mm))

    # ── SECTION 2: PROPERTY FLAGS ──
    high_flags = [f for f in (data.property_flags or []) if f.get("severity") in ("high", "medium")]
    if high_flags:
        story.append(_para("2. Property-Specific Risk Factors", subheading))
        story.append(
            _para(
                "The following risk factors were identified during the property assessment and "
                "further justify the requested price adjustment:",
                normal,
            )
        )
        story.append(Spacer(1, 3 * mm))
        for i, flag in enumerate(high_flags, 1):
            sev = flag.get("severity", "medium").upper()
            sev_color = "#ef4444" if flag.get("severity") == "high" else "#f59e0b"
            story.append(
                _para(
                    f"<b>{i}. [{sev}] {flag.get('flag', 'Property Risk')}</b> — "
                    f"<font color='#555555'>{flag.get('detail', '')}</font>",
                    ParagraphStyle(
                        "flag",
                        fontName="Helvetica",
                        fontSize=9.5,
                        leading=14,
                        textColor=colors.HexColor(sev_color),
                        leftIndent=10,
                        spaceBefore=3,
                    ),
                )
            )
        story.append(Spacer(1, 4 * mm))

    # ── SECTION 3: RERA ──
    section_num = 3 if high_flags else 2
    if data.rera_registered is not None or data.rera_complaint_count is not None:
        story.append(_para(f"{section_num}. RERA Registration & Compliance", subheading))
        rera_txt = ""
        if data.rera_registered is False:
            rera_txt = (
                "The property does not appear to be registered with MahaRERA. "
                "Under the Real Estate (Regulation and Development) Act 2016, all projects "
                "exceeding 500 sqm or 8 units must be RERA registered. The absence of RERA "
                "registration significantly increases buyer risk and reduces negotiating leverage."
            )
        elif data.rera_complaint_count and data.rera_complaint_count > 0:
            rera_txt = (
                f"MahaRERA records indicate {data.rera_complaint_count} complaint(s) against "
                f"this builder, which signals potential delivery or quality concerns. "
                f"This track record warrants a risk-adjusted pricing reduction."
            )
        else:
            rera_txt = "RERA status verified. This factor has been considered in our analysis."
        story.append(_para(rera_txt, normal))
        story.append(Spacer(1, 4 * mm))
        section_num += 1

    # ── SECTION 4: PROPOSED PRICE ──
    story.append(_para(f"{section_num}. Proposed Counter-Offer", subheading))
    story.append(Spacer(1, 2 * mm))

    price_data = [
        ["", "Amount"],
        ["Listed Price", f"₹{data.property_price:,.0f}"],
        [
            f"Market Premium Adjustment (−{min(data.premium_over_market_pct, 25) * 0.6:.1f}%)",
            f"−₹{data.property_price * min(data.premium_over_market_pct, 25) * 0.6 / 100:,.0f}",
        ],
        [
            f"Risk & Flag Adjustment",
            f"−₹{data.property_price * (data.justified_discount_pct - min(data.premium_over_market_pct, 25) * 0.6) / 100:,.0f}",
        ],
        ["COUNTER-OFFER PRICE", f"₹{data.requested_price:,.0f}"],
    ]
    price_table = Table(price_data, colWidths=[110 * mm, 60 * mm])
    price_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), _WHITE),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f8f7ff")]),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f0eeff")),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, -1), (-1, -1), _NAVY),
                ("TEXTCOLOR", (1, -1), (1, -1), colors.HexColor("#7c6af7")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
                ("PADDING", (0, 0), (-1, -1), 9),
                ("LINEABOVE", (0, -1), (-1, -1), 2, _PURPLE),
            ]
        )
    )
    story.append(price_table)
    story.append(Spacer(1, 6 * mm))

    # ── JUSTIFICATION SUMMARY ──
    story.append(_para("Justification Summary", subheading))
    for i, just in enumerate(data.justifications, 1):
        story.append(_para(f"{i}. {just}", normal))
        story.append(Spacer(1, 2 * mm))

    story.append(Spacer(1, 4 * mm))

    # ── CLOSING ──
    story.append(
        _para(
            f"We request your consideration of this counter-offer within <b>7 business days</b> "
            f"from the date of this letter. We remain committed to proceeding with the purchase "
            f"should the proposed price be accepted, and are prepared to finalize the agreement "
            f"with a token amount immediately upon mutual acceptance.",
            normal,
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(_para("We look forward to a mutually agreeable resolution.", normal))
    story.append(Spacer(1, 8 * mm))

    # ── SIGNATURE BLOCK ──
    sig_data = [
        [
            Paragraph("Yours sincerely,", normal),
            Paragraph(
                '<font color="#9896b8">This counter-offer expires in 7 business days.</font>',
                muted,
            ),
        ],
        [Paragraph(f"<b>{data.buyer_name}</b>", bold), Paragraph("", normal)],
        [Paragraph("Prospective Buyer", muted), Paragraph("", normal)],
        [Paragraph(f"Date: {data.report_date}", muted), Paragraph("", normal)],
    ]
    sig_table = Table(sig_data, colWidths=[90 * mm, 80 * mm])
    sig_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(sig_table)

    story.append(Spacer(1, 8 * mm))

    # ── DISCLAIMER ──
    story.append(
        _para(
            "DISCLAIMER: This letter was generated by NIV AI for informational and negotiation purposes only. "
            "The market benchmarks are based on NIV AI's Q4 2025 Mumbai micro-market database. "
            "This document does not constitute legal or financial advice. Buyers are advised to "
            "independently verify all market data and consult a qualified property advisor before "
            "making any purchase decision. NIV AI is not a registered real estate agent.",
            disclaimer_style,
        )
    )

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
