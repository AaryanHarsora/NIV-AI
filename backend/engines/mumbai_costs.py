"""
mumbai_costs.py — Mumbai-specific true cost calculator.

Covers all 10 cost layers for a Mumbai flat purchase:
    1. Property cost (base + floor rise + PLC + parking)
    2. Government charges (stamp duty + metro cess + registration)
    3. Legal and documentation costs
    4. Home loan costs
    5. Builder / society charges (GST + maintenance + corpus + clubhouse)
    6. Legal checks (placeholder flags — fed into legal_analyzer)
    7. Location-based reality (price per sqft vs market, rental yield)
    8. Hidden and ongoing costs (maintenance, property tax, interiors)
    9. First-time buyer risk flags
    10. Decision framework scores

No AI. Pure data and math. Deterministic output for same inputs every time.
"""

from dataclasses import dataclass, field
from typing import Optional


# ─── Mumbai stamp duty rates (2024-2025) ─────────────────────────────────────
# Male owner: 6% (5% stamp duty + 1% metro cess)
# Female owner: 5% (4% stamp duty + 1% metro cess)
# Joint (male+female): 5.5%
# We default to male rate as conservative estimate
STAMP_DUTY_RATE_MALE        = 0.05
STAMP_DUTY_RATE_FEMALE      = 0.04
STAMP_DUTY_RATE_JOINT       = 0.045
METRO_CESS_RATE             = 0.01   # applies to all Mumbai properties > ₹30L
REGISTRATION_RATE           = 0.01
REGISTRATION_CAP            = 30000.0   # Maharashtra cap

GST_UNDER_CONSTRUCTION      = 0.05   # 5% on UC, 0% on RTM
LOAN_PROCESSING_FEE_RATE    = 0.0075 # 0.75% of loan amount

# ─── Mumbai locality price benchmarks (₹ per sqft carpet area, 2025) ─────────
MUMBAI_LOCALITY_BENCHMARKS = {
    # South Mumbai
    "colaba":           (65000, 120000),
    "nariman point":    (70000, 130000),
    "malabar hill":     (60000, 110000),
    "worli":            (45000,  90000),
    "lower parel":      (35000,  65000),
    "prabhadevi":       (35000,  60000),
    # Western suburbs
    "bandra west":      (40000,  75000),
    "bandra east":      (25000,  45000),
    "khar":             (35000,  60000),
    "santacruz west":   (28000,  50000),
    "santacruz east":   (20000,  35000),
    "juhu":             (35000,  65000),
    "andheri west":     (20000,  35000),
    "andheri east":     (15000,  28000),
    "jogeshwari":       (14000,  24000),
    "goregaon":         (14000,  22000),
    "malad":            (12000,  20000),
    "kandivali":        (11000,  18000),
    "borivali":         (10000,  17000),
    "dahisar":          ( 8000,  14000),
    # Eastern suburbs
    "powai":            (18000,  28000),
    "vikhroli":         (12000,  20000),
    "kanjurmarg":       (12000,  18000),
    "bhandup":          (10000,  16000),
    "mulund":           (10000,  16000),
    "thane":            ( 8000,  15000),
    "ghodbunder road":  ( 7000,  12000),
    # Harbour line / CBD
    "kurla":            (10000,  18000),
    "chembur":          (12000,  20000),
    "ghatkopar":        (12000,  20000),
    "vikhroli":         (11000,  18000),
    # Navi Mumbai
    "vashi":            ( 9000,  16000),
    "kharghar":         ( 7000,  13000),
    "panvel":           ( 5000,  10000),
    "airoli":           ( 8000,  14000),
    "nerul":            ( 8000,  14000),
    "belapur":          ( 8000,  14000),
}

# ─── PLC (Preferential Location Charges) as % of base price ──────────────────
PLC_RATES = {
    "sea":      0.08,   # sea-facing: up to 8% premium
    "park":     0.05,   # park-facing: 5%
    "corner":   0.03,   # corner flat: 3%
    "road":     0.02,   # road-facing: 2%
    "internal": 0.00,   # internal/courtyard: no PLC
}

# ─── Mumbai flood zone localities (rough classification) ─────────────────────
HIGH_FLOOD_RISK_LOCALITIES = {
    "kurla", "sion", "matunga", "dadar", "parel",
    "hindmata", "andheri east", "jogeshwari east",
    "milan subway", "dahisar"
}

# ─── SRA / redevelopment risk localities ─────────────────────────────────────
HIGH_REDEVELOPMENT_RISK = {
    "dharavi", "kurla", "govandi", "mankhurd",
    "chembur east", "vikhroli east", "bhandup east"
}


# ─── Output dataclass ─────────────────────────────────────────────────────────

@dataclass
class MumbaiCostBreakdown:

    # ── Layer 1: Property cost ────────────────────────────────────────────────
    base_price:                 float
    floor_rise_charges:         float
    plc_charges:                float
    parking_cost:               float
    advertised_total:           float   # what builder/seller quotes

    # ── Layer 2: Government charges ───────────────────────────────────────────
    stamp_duty:                 float
    metro_cess:                 float
    registration_fee:           float
    total_govt_charges:         float

    # ── Layer 3: Legal and documentation ─────────────────────────────────────
    lawyer_fees:                float
    agreement_drafting:         float
    due_diligence_fee:          float
    total_legal_costs:          float

    # ── Layer 4: Loan costs ───────────────────────────────────────────────────
    loan_amount:                float
    loan_processing_fee:        float
    loan_insurance_estimate:    float
    total_loan_costs:           float

    # ── Layer 5: Builder / society charges ────────────────────────────────────
    gst:                        float
    maintenance_deposit:        float   # 1-2 years upfront
    society_formation_charges:  float
    corpus_fund:                float
    clubhouse_fee:              float
    total_builder_charges:      float

    # ── Layer 7: Location reality ─────────────────────────────────────────────
    locality:                   str
    price_per_sqft_actual:      float
    market_price_per_sqft_low:  float
    market_price_per_sqft_high: float
    price_vs_market:            str     # "below", "at", "above", "unknown"
    price_premium_pct:          float   # how much above/below market mid
    estimated_rental_yield_pct: float   # Mumbai average 2-3%
    estimated_monthly_rent:     float

    # ── Layer 8: Ongoing costs ────────────────────────────────────────────────
    monthly_maintenance:        float
    annual_property_tax:        float
    interior_estimate:          float
    total_first_year_ongoing:   float

    # ── Layer 9: Risk flags ───────────────────────────────────────────────────
    flood_zone_risk:            bool
    redevelopment_risk:         bool
    is_under_construction:      bool
    risk_flags:                 list

    # ── Summary ───────────────────────────────────────────────────────────────
    true_total_acquisition_cost:    float   # everything to get keys
    true_total_with_interiors:      float   # including interior fit-out
    hidden_cost_above_advertised:   float   # advertised vs true
    hidden_cost_percentage:         float   # how much % more than quoted
    cost_breakdown_text:            str     # plain English one-liner


def calculate_mumbai_true_cost(
    base_price:             float,
    area_sqft:              float,
    floor_number:           int,
    property_type:          str,            # "under_construction" | "ready_to_move"
    facing:                 str,            # "sea"|"park"|"corner"|"road"|"internal"
    parking_included:       bool,
    parking_cost:           float,          # 0 if included
    loan_amount:            float,
    locality:               str   = "andheri west",
    owner_gender:           str   = "male", # "male"|"female"|"joint"
    maintenance_per_sqft:   float = 8.0,    # ₹8-15/sqft in Mumbai
    interior_budget:        float = 800000, # ₹8L default estimate
    include_loan_insurance: bool  = True,
) -> MumbaiCostBreakdown:
    """
    Calculate the complete true cost of buying a Mumbai flat.
    Every rupee figure is computed in Python — no LLM arithmetic.
    """

    locality_key = locality.lower().strip()

    # ── Layer 1: Property cost ────────────────────────────────────────────────

    # Floor rise: Mumbai builders charge ₹50-150/sqft per floor above ground
    # Conservative: ₹75/sqft per floor for floors 2-10, ₹100 above 10th
    floors_above_ground = max(0, floor_number - 1)
    if floors_above_ground == 0:
        floor_rise_charges = 0.0
    elif floors_above_ground <= 10:
        floor_rise_charges = area_sqft * 75 * floors_above_ground
    else:
        floor_rise_charges = (
            area_sqft * 75 * 10 +
            area_sqft * 100 * (floors_above_ground - 10)
        )

    # PLC
    plc_rate     = PLC_RATES.get(facing.lower(), 0.0)
    plc_charges  = base_price * plc_rate

    # Parking
    if parking_included:
        parking_cost = 0.0
    # else use the passed value directly

    advertised_total = base_price + floor_rise_charges + plc_charges + parking_cost

    # ── Layer 2: Government charges ───────────────────────────────────────────

    stamp_rate_map = {
        "male":   STAMP_DUTY_RATE_MALE,
        "female": STAMP_DUTY_RATE_FEMALE,
        "joint":  STAMP_DUTY_RATE_JOINT,
    }
    stamp_duty_rate = stamp_rate_map.get(owner_gender.lower(), STAMP_DUTY_RATE_MALE)

    stamp_duty      = advertised_total * stamp_duty_rate
    metro_cess      = advertised_total * METRO_CESS_RATE
    registration_fee = min(advertised_total * REGISTRATION_RATE, REGISTRATION_CAP)
    total_govt_charges = stamp_duty + metro_cess + registration_fee

    # ── Layer 3: Legal costs ──────────────────────────────────────────────────

    # Mumbai lawyer fees: 0.5% of property value, min ₹15K
    lawyer_fees        = max(advertised_total * 0.005, 15000.0)
    agreement_drafting = 25000.0
    due_diligence_fee  = 15000.0   # title search + dispute check
    total_legal_costs  = lawyer_fees + agreement_drafting + due_diligence_fee

    # ── Layer 4: Loan costs ───────────────────────────────────────────────────

    loan_processing_fee     = loan_amount * LOAN_PROCESSING_FEE_RATE
    loan_insurance_estimate = (loan_amount * 0.004) if include_loan_insurance else 0.0
    total_loan_costs        = loan_processing_fee + loan_insurance_estimate

    # ── Layer 5: Builder / society charges ────────────────────────────────────

    # GST only on under-construction
    gst = advertised_total * GST_UNDER_CONSTRUCTION if property_type == "under_construction" else 0.0

    # Maintenance deposit: typically 24 months upfront in Mumbai
    maintenance_deposit       = maintenance_per_sqft * area_sqft * 24
    society_formation_charges = 25000.0
    corpus_fund               = area_sqft * 150.0   # ₹100-200/sqft typical
    clubhouse_fee             = 75000.0             # Mumbai average

    total_builder_charges = (
        gst + maintenance_deposit + society_formation_charges +
        corpus_fund + clubhouse_fee
    )

    # ── Layer 7: Location reality ─────────────────────────────────────────────

    market_low, market_high = MUMBAI_LOCALITY_BENCHMARKS.get(
        locality_key, (0, 0)
    )
    price_per_sqft_actual = base_price / area_sqft if area_sqft > 0 else 0

    if market_low == 0:
        price_vs_market   = "unknown"
        price_premium_pct = 0.0
    else:
        market_mid        = (market_low + market_high) / 2
        price_premium_pct = ((price_per_sqft_actual - market_mid) / market_mid) * 100
        if price_per_sqft_actual < market_low:
            price_vs_market = "below"
        elif price_per_sqft_actual > market_high:
            price_vs_market = "above"
        else:
            price_vs_market = "at"

    # Mumbai rental yield: 2-3% gross annually
    estimated_rental_yield_pct = 2.5
    estimated_monthly_rent     = (base_price * 0.025) / 12

    # ── Layer 8: Ongoing costs ────────────────────────────────────────────────

    monthly_maintenance      = maintenance_per_sqft * area_sqft
    annual_property_tax      = base_price * 0.001   # ~0.1% of market value
    total_first_year_ongoing = (monthly_maintenance * 12) + annual_property_tax

    # ── Layer 9: Risk flags ───────────────────────────────────────────────────

    flood_zone_risk      = locality_key in HIGH_FLOOD_RISK_LOCALITIES
    redevelopment_risk   = locality_key in HIGH_REDEVELOPMENT_RISK
    is_under_construction = property_type == "under_construction"

    risk_flags = []
    if flood_zone_risk:
        risk_flags.append(
            f"{locality.title()} is in a known flood-risk zone. "
            "Verify BMC flood maps before buying."
        )
    if redevelopment_risk:
        risk_flags.append(
            f"{locality.title()} has active SRA/redevelopment projects. "
            "Verify the building is not under any redevelopment notice."
        )
    if is_under_construction:
        risk_flags.append(
            "Under-construction property. Verify RERA registration on MahaRERA. "
            "Builder delays are common — check past delivery history."
        )
    if price_vs_market == "above":
        risk_flags.append(
            f"Price per sqft (₹{price_per_sqft_actual:,.0f}) is above the "
            f"{locality.title()} market range "
            f"(₹{market_low:,}–₹{market_high:,}/sqft). "
            "Negotiate or verify what premium is justified."
        )
    if parking_cost > 500000:
        risk_flags.append(
            f"Parking at ₹{parking_cost:,.0f} is high. "
            "Confirm this is a covered, deeded parking spot."
        )

    # ── Summary ───────────────────────────────────────────────────────────────

    true_total_acquisition_cost = (
        advertised_total
        + total_govt_charges
        + total_legal_costs
        + total_loan_costs
        + total_builder_charges
    )

    true_total_with_interiors    = true_total_acquisition_cost + interior_budget
    hidden_cost_above_advertised = true_total_acquisition_cost - advertised_total
    hidden_cost_percentage       = (
        hidden_cost_above_advertised / advertised_total * 100
        if advertised_total > 0 else 0
    )

    cost_breakdown_text = (
        f"You quoted ₹{advertised_total/1e5:.1f}L but the true cost to "
        f"get the keys is ₹{true_total_acquisition_cost/1e5:.1f}L — "
        f"₹{hidden_cost_above_advertised/1e5:.1f}L "
        f"({hidden_cost_percentage:.1f}%) more than advertised. "
        f"With interiors it becomes ₹{true_total_with_interiors/1e5:.1f}L."
    )

    return MumbaiCostBreakdown(
        base_price=base_price,
        floor_rise_charges=round(floor_rise_charges, 2),
        plc_charges=round(plc_charges, 2),
        parking_cost=round(parking_cost, 2),
        advertised_total=round(advertised_total, 2),

        stamp_duty=round(stamp_duty, 2),
        metro_cess=round(metro_cess, 2),
        registration_fee=round(registration_fee, 2),
        total_govt_charges=round(total_govt_charges, 2),

        lawyer_fees=round(lawyer_fees, 2),
        agreement_drafting=round(agreement_drafting, 2),
        due_diligence_fee=round(due_diligence_fee, 2),
        total_legal_costs=round(total_legal_costs, 2),

        loan_amount=round(loan_amount, 2),
        loan_processing_fee=round(loan_processing_fee, 2),
        loan_insurance_estimate=round(loan_insurance_estimate, 2),
        total_loan_costs=round(total_loan_costs, 2),

        gst=round(gst, 2),
        maintenance_deposit=round(maintenance_deposit, 2),
        society_formation_charges=round(society_formation_charges, 2),
        corpus_fund=round(corpus_fund, 2),
        clubhouse_fee=round(clubhouse_fee, 2),
        total_builder_charges=round(total_builder_charges, 2),

        locality=locality,
        price_per_sqft_actual=round(price_per_sqft_actual, 2),
        market_price_per_sqft_low=market_low,
        market_price_per_sqft_high=market_high,
        price_vs_market=price_vs_market,
        price_premium_pct=round(price_premium_pct, 1),
        estimated_rental_yield_pct=estimated_rental_yield_pct,
        estimated_monthly_rent=round(estimated_monthly_rent, 2),

        monthly_maintenance=round(monthly_maintenance, 2),
        annual_property_tax=round(annual_property_tax, 2),
        interior_estimate=round(interior_budget, 2),
        total_first_year_ongoing=round(total_first_year_ongoing, 2),

        flood_zone_risk=flood_zone_risk,
        redevelopment_risk=redevelopment_risk,
        is_under_construction=is_under_construction,
        risk_flags=risk_flags,

        true_total_acquisition_cost=round(true_total_acquisition_cost, 2),
        true_total_with_interiors=round(true_total_with_interiors, 2),
        hidden_cost_above_advertised=round(hidden_cost_above_advertised, 2),
        hidden_cost_percentage=round(hidden_cost_percentage, 1),
        cost_breakdown_text=cost_breakdown_text,
    )


# ─── Quick sanity test ────────────────────────────────────────────────────────
if __name__ == "__main__":
    result = calculate_mumbai_true_cost(
        base_price=12000000,       # ₹1.2 Cr
        area_sqft=750,
        floor_number=8,
        property_type="ready_to_move",
        facing="park",
        parking_included=False,
        parking_cost=500000,       # ₹5L
        loan_amount=9000000,       # ₹90L
        locality="powai",
        owner_gender="male",
    )

    print(f"\n{'='*60}")
    print(f"TEST: ₹1.2Cr flat in Powai, 8th floor, park-facing")
    print(f"{'='*60}")
    print(f"\n── Layer 1: Property Cost")
    print(f"  Base price:           ₹{result.base_price:>12,.0f}")
    print(f"  Floor rise (7 floors):₹{result.floor_rise_charges:>12,.0f}")
    print(f"  PLC (park 5%):        ₹{result.plc_charges:>12,.0f}")
    print(f"  Parking:              ₹{result.parking_cost:>12,.0f}")
    print(f"  Advertised total:     ₹{result.advertised_total:>12,.0f}")
    print(f"\n── Layer 2: Govt Charges")
    print(f"  Stamp duty (5%):      ₹{result.stamp_duty:>12,.0f}")
    print(f"  Metro cess (1%):      ₹{result.metro_cess:>12,.0f}")
    print(f"  Registration (capped):₹{result.registration_fee:>12,.0f}")
    print(f"\n── Layer 3: Legal")
    print(f"  Lawyer fees:          ₹{result.lawyer_fees:>12,.0f}")
    print(f"  Agreement drafting:   ₹{result.agreement_drafting:>12,.0f}")
    print(f"  Due diligence:        ₹{result.due_diligence_fee:>12,.0f}")
    print(f"\n── Layer 4: Loan Costs")
    print(f"  Processing fee:       ₹{result.loan_processing_fee:>12,.0f}")
    print(f"  Insurance estimate:   ₹{result.loan_insurance_estimate:>12,.0f}")
    print(f"\n── Layer 5: Builder/Society")
    print(f"  GST (RTM = 0%):       ₹{result.gst:>12,.0f}")
    print(f"  Maintenance deposit:  ₹{result.maintenance_deposit:>12,.0f}")
    print(f"  Society formation:    ₹{result.society_formation_charges:>12,.0f}")
    print(f"  Corpus fund:          ₹{result.corpus_fund:>12,.0f}")
    print(f"  Clubhouse fee:        ₹{result.clubhouse_fee:>12,.0f}")
    print(f"\n── Layer 7: Location")
    print(f"  Price/sqft actual:    ₹{result.price_per_sqft_actual:>12,.0f}")
    print(f"  Market range (Powai): ₹{result.market_price_per_sqft_low:,} – ₹{result.market_price_per_sqft_high:,}")
    print(f"  Price vs market:      {result.price_vs_market.upper()} ({result.price_premium_pct:+.1f}%)")
    print(f"  Est. monthly rent:    ₹{result.estimated_monthly_rent:>12,.0f}")
    print(f"\n── Layer 8: Ongoing (annual)")
    print(f"  Monthly maintenance:  ₹{result.monthly_maintenance:>12,.0f}/mo")
    print(f"  Property tax:         ₹{result.annual_property_tax:>12,.0f}/yr")
    print(f"\n── Summary")
    print(f"  TRUE ACQUISITION COST:₹{result.true_total_acquisition_cost:>12,.0f}")
    print(f"  WITH INTERIORS:       ₹{result.true_total_with_interiors:>12,.0f}")
    print(f"  HIDDEN ABOVE QUOTED:  ₹{result.hidden_cost_above_advertised:>12,.0f} ({result.hidden_cost_percentage:.1f}%)")
    print(f"\n── Risk Flags")
    for flag in result.risk_flags:
        print(f"  ⚠  {flag}")
    print(f"\n{result.cost_breakdown_text}")
    print(f"{'='*60}")