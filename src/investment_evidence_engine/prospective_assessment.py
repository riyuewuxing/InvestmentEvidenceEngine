"""Read-only descriptive assessment of a fixed prospective daily cohort.

Inputs are directions and observed raw open-to-close labels supplied by a
caller that has independently verified its immutable records and source
bytes. This module cannot verify a caller's event store, calibrate a
probability, infer fills, or admit a model. Missing sessions and outcomes
remain in denominators. No account data or strategy execution is required.
"""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from .historical_capture import SH
from .market_calendar import SCHEDULE_VERSION, scheduled_days

Direction = Literal["UP", "DOWN", "FLAT"]
DIRECTIONS = ("UP", "DOWN", "FLAT")
THRESHOLD = Decimal("0.001")
Outcome = Literal["PENDING", "OBSERVED", "UNAVAILABLE", "UNTRADEABLE", "NOT_TRIGGERED", "EXPIRED"]


class DailyAssessmentRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    subject_id: str = Field(pattern=r"^[0-9]{6}$")
    disposition: Literal["SELECTED", "REJECTED", "UNAVAILABLE"]
    direction: Direction | None = None
    outcome_status: Outcome
    observed_return: FiniteFloat | None = Field(default=None, gt=-1)

    @model_validator(mode="after")
    def consistent(self) -> DailyAssessmentRow:
        if (self.disposition == "SELECTED") != (self.direction is not None):
            raise ValueError("ASSESSMENT_SELECTION_MISMATCH")
        if (self.outcome_status == "OBSERVED") != (self.observed_return is not None):
            raise ValueError("ASSESSMENT_OUTCOME_MISMATCH")
        return self


class DailyAssessmentBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    session: date
    rows: tuple[DailyAssessmentRow, ...] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def consistent(self) -> DailyAssessmentBatch:
        if len({r.subject_id for r in self.rows}) != len(self.rows):
            raise ValueError("ASSESSMENT_DUPLICATE_SUBJECT")
        pending = sum(r.outcome_status == "PENDING" for r in self.rows)
        if pending not in (0, len(self.rows)):
            raise ValueError("ASSESSMENT_PARTIAL_FINALIZATION")
        return self


def actual_direction(value: float) -> str:
    value = Decimal(str(value))
    return "UP" if value > THRESHOLD else "DOWN" if value < -THRESHOLD else "FLAT"


def assess_daily_cohort(first: date, last: date, symbols: tuple[str, ...],
                        batches: tuple[DailyAssessmentBatch, ...], *, now: datetime) -> dict:
    """One fixed cohort, one forecast per session, one fixed flat benchmark.

    Coverage is relative to the published annual calendar, not proof that
    every session occurred or that the chosen interval was pre-registered.
    """
    if now.utcoffset() is None or not 0 <= (last-first).days <= 90:
        raise ValueError("ASSESSMENT_RANGE_OR_TIME_INVALID")
    local = now.astimezone(SH)
    if last > local.date() or (last == local.date() and local.time() < time(15, 0)):
        raise ValueError("ASSESSMENT_HORIZON_NOT_MATURED")
    if not 1 <= len(symbols) <= 5 or len(set(symbols)) != len(symbols):
        raise ValueError("ASSESSMENT_COHORT_INVALID")
    if any(len(s) != 6 or not s.isascii() or not s.isdigit() for s in symbols):
        raise ValueError("ASSESSMENT_SUBJECT_INVALID")
    expected = tuple(d.day for d in scheduled_days(first,last) if d.is_trading_day)
    if not expected:
        raise ValueError("ASSESSMENT_NO_SCHEDULED_SESSIONS")
    records = {}
    for batch in batches:
        b = DailyAssessmentBatch.model_validate(batch.model_dump())
        if b.session not in expected or b.session in records:
            raise ValueError("ASSESSMENT_DUPLICATE_OR_UNSCHEDULED_SESSION")
        if tuple(r.subject_id for r in b.rows) != symbols:
            raise ValueError("ASSESSMENT_FIXED_COHORT_MISMATCH")
        records[b.session] = b
    total = len(expected)*len(symbols)
    missing_sessions = [d.isoformat() for d in expected if d not in records]
    disposition = {k:0 for k in ("SELECTED","REJECTED","UNAVAILABLE")}
    outcomes = {k:0 for k in ("PENDING","OBSERVED","UNAVAILABLE","UNTRADEABLE","NOT_TRIGGERED","EXPIRED")}
    confusion = {p:{a:0 for a in DIRECTIONS} for p in DIRECTIONS}
    observed_selected = hits = flat_hits = 0
    daily = []
    for day in expected:
        b = records.get(day)
        if b is None:
            daily.append({"session":day.isoformat(),"status":"NO_FROZEN_BATCH"})
            continue
        n = h = f = 0
        for r in b.rows:
            disposition[r.disposition] += 1
            outcomes[r.outcome_status] += 1
            if r.disposition == "SELECTED" and r.outcome_status == "OBSERVED":
                actual = actual_direction(r.observed_return)
                confusion[r.direction][actual] += 1
                n += 1
                h += int(r.direction == actual)
                f += int(actual == "FLAT")
        observed_selected += n
        hits += h
        flat_hits += f
        complete = n == len(symbols)
        daily.append({"session":day.isoformat(),"status":"COMPLETE_PAIRED_COHORT" if complete else "INCOMPLETE_PAIRED_COHORT",
                      "observed_selected":n,"correct":h,"flat_correct":f,
                      "paired_complete_accuracy":h/n if complete else None,
                      "paired_complete_flat_accuracy":f/n if complete else None})
    selected = disposition["SELECTED"]
    complete_days = [d for d in daily if d["status"] == "COMPLETE_PAIRED_COHORT"]
    # Missing outcomes for actually frozen predictions have a finite
    # arithmetic worst/best accuracy envelope. Missing whole sessions
    # are NOT assigned a hypothetical direction or counted as failures.
    missing_selected = selected-observed_selected
    complete_diff = sum(d["paired_complete_accuracy"]-d["paired_complete_flat_accuracy"] for d in complete_days)
    return {"status":"DESCRIPTIVE_PROSPECTIVE_ASSESSMENT_ONLY","calendar_basis":SCHEDULE_VERSION,
            "first":first.isoformat(),"last":last.isoformat(),"expected_sessions":len(expected),
            "frozen_sessions":len(records),"missing_sessions":missing_sessions,"fixed_symbols":list(symbols),
            "expected_subject_session_slots":total,"unfrozen_slots":len(missing_sessions)*len(symbols),
            "disposition_counts":disposition,"outcome_counts":outcomes,"observed_selected_count":observed_selected,
            "observed_selected_accuracy":hits/observed_selected if observed_selected else None,
            "observed_selected_flat_accuracy":flat_hits/observed_selected if observed_selected else None,
            "selected_accuracy_bounds_from_missing_outcomes":[hits/selected,(hits+missing_selected)/selected] if selected else None,
            "full_scheduled_evaluable_coverage":observed_selected/total,
            "complete_paired_session_count":len(complete_days),
            "complete_session_mean_accuracy_difference":complete_diff/len(complete_days) if complete_days else None,
            "confusion_predicted_by_actual":confusion,"sessions":daily,
            "interval_preregistration_verified":False,"event_source_verification_by_caller_required":True,
            "probability_calibrated":False,"statistical_significance_estimated":False,
            "independence_assumed":False,"actual_fill_or_net_return_estimated":False,
            "research_only":True,"execution_allowed":False}
