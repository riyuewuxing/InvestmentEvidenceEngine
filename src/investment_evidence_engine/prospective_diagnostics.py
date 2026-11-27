"""Paired descriptive sensitivity to missing outcomes, not a skill estimate.

The same observed labels score both the fixed forecast and the flat control.
For a missing selected observation, a directional forecast may outperform
or underperform FLAT by one; a FLAT forecast is identical to the control.
No outcomes or predictions are imputed, and no unfrozen slots are scored.
"""
from __future__ import annotations

from datetime import date, datetime

from .prospective_assessment import (
    DailyAssessmentBatch,
    actual_direction,
    assess_daily_cohort,
)


def assess_paired_direction_delta(
    first: date,
    last: date,
    symbols: tuple[str, ...],
    batches: tuple[DailyAssessmentBatch, ...],
    *,
    now: datetime,
) -> dict:
    coverage = assess_daily_cohort(first, last, symbols, batches, now=now)
    delta = 0
    observed = missing_directional = missing_flat = 0
    for raw in batches:
        batch = DailyAssessmentBatch.model_validate(raw.model_dump())
        for row in batch.rows:
            if row.disposition != "SELECTED":
                continue
            if row.outcome_status != "OBSERVED":
                if row.direction == "FLAT":
                    missing_flat += 1
                else:
                    missing_directional += 1
                continue
            actual = actual_direction(row.observed_return)
            delta += int(row.direction == actual) - int(actual == "FLAT")
            observed += 1
    selected = observed + missing_directional + missing_flat
    return {
        "status": "DESCRIPTIVE_PAIRED_DELTA_ONLY",
        "selected_slots": selected,
        "observed_selected_slots": observed,
        "missing_selected_directional_slots": missing_directional,
        "missing_selected_flat_slots": missing_flat,
        "unfrozen_slots_not_scored": coverage["unfrozen_slots"],
        "full_scheduled_evaluable_coverage": coverage["full_scheduled_evaluable_coverage"],
        "observed_paired_accuracy_delta": delta / observed if observed else None,
        "selected_paired_accuracy_delta_bounds": [
            (delta - missing_directional) / selected,
            (delta + missing_directional) / selected,
        ] if selected else None,
        "interval_preregistration_verified": False,
        "source_bytes_verified": False,
        "confidence_interval_estimated": False,
        "independence_assumed": False,
        "probability_calibrated": False,
        "model_promotion_allowed": False,
        "research_only": True,
        "execution_allowed": False,
    }
