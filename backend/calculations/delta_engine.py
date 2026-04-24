"""
Delta tracking engine — computes meaningful changes between two
computed states. Powers the what-if slider delta badges and
sensitivity analysis in the frontend.
"""

from __future__ import annotations

from typing import Optional

FINANCIAL_STATE_THRESHOLDS = {
    "stable":   {"emi_ratio": 0.30, "runway": 6.0, "dp_ratio": 0.60},
    "strained": {"emi_ratio": 0.40, "runway": 4.0, "dp_ratio": 0.75},
    "fragile":  {"emi_ratio": 0.50, "runway": 2.5, "dp_ratio": 0.85},
    "critical": {"emi_ratio": 0.60, "runway": 1.0, "dp_ratio": 1.00},
}

_STATE_ORDER = ["Stable", "Strained", "Fragile", "Critical"]

# Decrease = improvement for these metrics
_LOWER_IS_BETTER = {
    "monthly_emi",
    "emi_to_income_ratio",
    "monthly_ownership_cost",
    "total_acquisition_cost",
    "down_payment_opportunity_cost_10yr",
}

# Increase = improvement for these metrics
_HIGHER_IS_BETTER = {
    "emergency_runway_months",
    "post_purchase_savings",
}

_TRACKED_METRICS = sorted(_LOWER_IS_BETTER | _HIGHER_IS_BETTER)

_METRIC_LABELS = {
    "monthly_emi": "EMI",
    "emi_to_income_ratio": "EMI-to-income ratio",
    "emergency_runway_months": "emergency runway",
    "monthly_ownership_cost": "monthly ownership cost",
    "total_acquisition_cost": "total acquisition cost",
    "post_purchase_savings": "post-purchase savings",
    "down_payment_opportunity_cost_10yr": "10-yr opportunity cost",
}

_EMI_THRESHOLDS = [(0.30, "30%_emi"), (0.40, "40%_emi"), (0.50, "50%_emi"), (0.60, "60%_emi")]
_RUNWAY_THRESHOLDS = [(6.0, "6mo_runway"), (4.0, "4mo_runway"), (2.5, "2.5mo_runway"), (1.0, "1mo_runway")]


def classify_financial_state(computed: dict) -> str:
    """
    Maps computed metrics to one of four states:
    Stable → Strained → Fragile → Critical

    State is determined by the WORST of the three sub-metrics.

    Returns: "Stable" | "Strained" | "Fragile" | "Critical"
    """
    emi_ratio = computed.get("emi_to_income_ratio") or 0.0
    runway = computed.get("emergency_runway_months") or 99.0
    dp_ratio = computed.get("down_payment_to_savings_ratio") or 0.0

    if emi_ratio > 0.50 or runway < 2.5 or dp_ratio > 0.85:
        return "Critical"
    if emi_ratio > 0.40 or runway < 4.0 or dp_ratio > 0.75:
        return "Fragile"
    if emi_ratio > 0.30 or runway < 6.0 or dp_ratio > 0.60:
        return "Strained"
    return "Stable"


def _direction(metric: str, delta_abs: float) -> str:
    if delta_abs == 0:
        return "unchanged"
    if metric in _LOWER_IS_BETTER:
        return "improved" if delta_abs < 0 else "worsened"
    return "improved" if delta_abs > 0 else "worsened"


def _emi_threshold_crossed(before: float, after: float) -> Optional[str]:
    for t, label in _EMI_THRESHOLDS:
        if (before <= t < after) or (after <= t < before):
            return label
    return None


def _runway_threshold_crossed(before: float, after: float) -> Optional[str]:
    for t, label in _RUNWAY_THRESHOLDS:
        if (before >= t > after) or (after >= t > before):
            return label
    return None


def compute_delta(before: dict, after: dict) -> dict:
    """
    Computes the delta between two computed_numbers dicts.
    Used by what-if sliders to show change badges.

    For each tracked metric, returns:
    - before, after: raw values
    - absolute: after - before
    - pct_change: % change relative to before
    - direction: "improved" | "worsened" | "unchanged"
    - crossed_threshold: bool
    - threshold_crossed: str | None

    Tracked metrics:
    monthly_emi, emi_to_income_ratio, emergency_runway_months,
    monthly_ownership_cost, total_acquisition_cost,
    post_purchase_savings, down_payment_opportunity_cost_10yr

    Returns dict with:
    - deltas: per-metric breakdown
    - state_before, state_after: from classify_financial_state
    - state_changed: bool
    - state_direction: "improved" | "worsened" | "unchanged"
    - summary: plain-English sentence of the key change
    - most_impactful_change: single biggest improvement or worsening
    """
    deltas: dict = {}
    for metric in _TRACKED_METRICS:
        v_before = before.get(metric) or 0.0
        v_after = after.get(metric) or 0.0
        delta_abs = round(v_after - v_before, 4)
        pct_change = round(delta_abs / v_before * 100, 2) if v_before != 0 else 0.0
        dir_ = _direction(metric, delta_abs)

        threshold_label: Optional[str] = None
        if metric == "emi_to_income_ratio":
            threshold_label = _emi_threshold_crossed(v_before, v_after)
        elif metric == "emergency_runway_months":
            threshold_label = _runway_threshold_crossed(v_before, v_after)

        deltas[metric] = {
            "before": v_before,
            "after": v_after,
            "absolute": delta_abs,
            "pct_change": pct_change,
            "direction": dir_,
            "crossed_threshold": threshold_label is not None,
            "threshold_crossed": threshold_label,
        }

    state_before = classify_financial_state(before)
    state_after = classify_financial_state(after)
    state_changed = state_before != state_after

    if not state_changed:
        state_direction = "unchanged"
    elif _STATE_ORDER.index(state_after) < _STATE_ORDER.index(state_before):
        state_direction = "improved"
    else:
        state_direction = "worsened"

    # Largest absolute % change among non-unchanged metrics
    max_impact_metric: Optional[str] = None
    max_impact_pct = 0.0
    for metric, d in deltas.items():
        if d["direction"] != "unchanged" and abs(d["pct_change"]) > max_impact_pct:
            max_impact_pct = abs(d["pct_change"])
            max_impact_metric = metric

    emi_d = deltas["monthly_emi"]
    runway_d = deltas["emergency_runway_months"]
    parts = []
    if emi_d["direction"] != "unchanged":
        verb = "drops" if emi_d["absolute"] < 0 else "rises"
        parts.append(f"EMI {verb} by ₹{abs(emi_d['absolute']):,.0f}/mo")
    if runway_d["direction"] != "unchanged":
        verb = "improves" if runway_d["direction"] == "improved" else "drops"
        parts.append(f"runway {verb} to {runway_d['after']:.1f} months")
    if parts:
        raw = " and ".join(parts)
        summary = raw[0].upper() + raw[1:] + "."
    else:
        summary = "No significant change in key metrics."

    if max_impact_metric:
        d = deltas[max_impact_metric]
        label = _METRIC_LABELS.get(max_impact_metric, max_impact_metric)
        verb = "improves" if d["direction"] == "improved" else "worsens"
        most_impactful = f"{label} {verb} by {abs(d['pct_change']):.1f}%."
    else:
        most_impactful = "No significant change."

    return {
        "deltas": deltas,
        "state_before": state_before,
        "state_after": state_after,
        "state_changed": state_changed,
        "state_direction": state_direction,
        "summary": summary,
        "most_impactful_change": most_impactful,
    }


def compute_survival_timeline(
    monthly_income: float,
    monthly_burn: float,
    liquid_savings: float,
    post_purchase_savings: float,
    monthly_emi: float,
) -> dict:
    """
    Computes month-by-month survival under job loss scenario.

    Simulates savings depleting by monthly_burn each month starting from
    post_purchase_savings. Tracks when savings hit zero (default point).

    Returns dict with:
    - months_before_default: int (0 if already critical)
    - default_month: int | None (None if survives all 24 simulated months)
    - monthly_snapshots: list of {month, savings_remaining, pct_remaining} for months 1-12
    - survival_probability_label: "Very High" | "High" | "Medium" | "Low" | "Critical"
    - savings_depletion_rate: float (% of initial savings depleted per month)
    """
    if monthly_burn <= 0:
        return {
            "months_before_default": 24,
            "default_month": None,
            "monthly_snapshots": [],
            "survival_probability_label": "Very High",
            "savings_depletion_rate": 0.0,
        }

    if post_purchase_savings <= 0:
        return {
            "months_before_default": 0,
            "default_month": 1,
            "monthly_snapshots": [{"month": 1, "savings_remaining": 0.0, "pct_remaining": 0.0}],
            "survival_probability_label": "Critical",
            "savings_depletion_rate": 100.0,
        }

    depletion_rate = round(monthly_burn / post_purchase_savings * 100, 2)
    snapshots = []
    remaining = post_purchase_savings
    default_month: Optional[int] = None
    months_before_default = 0

    for month in range(1, 25):
        remaining -= monthly_burn
        if remaining <= 0:
            default_month = month
            months_before_default = month - 1
            if month <= 12:
                snapshots.append({"month": month, "savings_remaining": 0.0, "pct_remaining": 0.0})
            break
        if month <= 12:
            snapshots.append({
                "month": month,
                "savings_remaining": round(remaining, 2),
                "pct_remaining": round(remaining / post_purchase_savings * 100, 1),
            })
    else:
        # Loop completed without default — survived 24 months
        months_before_default = 24

    if months_before_default >= 12:
        label = "Very High"
    elif months_before_default >= 8:
        label = "High"
    elif months_before_default >= 4:
        label = "Medium"
    elif months_before_default >= 2:
        label = "Low"
    else:
        label = "Critical"

    return {
        "months_before_default": months_before_default,
        "default_month": default_month,
        "monthly_snapshots": snapshots,
        "survival_probability_label": label,
        "savings_depletion_rate": depletion_rate,
    }
