"""A preregistration envelope over the existing daily assessment, not a new model.

Content and temporal checks do not authenticate a caller's Git/event history.
The caller must independently verify the registration commit, first-run
provenance, source bytes and completeness of the append-only records.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .historical_capture import SH
from .market_calendar import SCHEDULE_VERSION, scheduled_days
from .prospective_assessment import DailyAssessmentBatch, assess_daily_cohort

SHA = r"^[a-f0-9]{64}$"


class CohortProtocol(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    protocol_id: str = Field(pattern=r"^[a-z0-9_]{8,80}$")
    registered_at: AwareDatetime
    first: date
    last: date
    symbols: tuple[str, ...] = Field(min_length=1, max_length=5)
    strategy: Literal["daily_intraday_persistence_5"]
    strategy_version: Literal["1.0"]
    threshold: Literal["0.001"]
    benchmark: Literal["FLAT"]
    label: Literal["RAW_OPEN_TO_CLOSE_GROSS_NOT_EXECUTABLE_TRADE"]
    planning_rule: Literal["PREVIOUS_CALENDAR_DAY_EXCLUDE_PLANNING_DAY"]
    source: Literal["baostock_unadjusted_daily"]
    calendar_version: Literal["SSE_SZSE_2025_2026_ANNUAL_NOTICES_V1"]
    first_attempt_only: Literal[True]
    no_backfill: Literal[True]
    research_only: Literal[True]
    execution_allowed: Literal[False]

    def sessions(self) -> tuple[date, ...]:
        return tuple(row.day for row in scheduled_days(self.first, self.last) if row.is_trading_day)

    @model_validator(mode="after")
    def validate_protocol(self) -> CohortProtocol:
        if not 0 <= (self.last - self.first).days <= 90:
            raise ValueError("PROTOCOL_RANGE")
        sessions = self.sessions()
        if not sessions or sessions[0] != self.first or sessions[-1] != self.last:
            raise ValueError("PROTOCOL_ENDPOINTS_NOT_SESSIONS")
        if self.registered_at >= planning_start(self.first):
            raise ValueError("PROTOCOL_REGISTRATION_TOO_LATE")
        if self.calendar_version != SCHEDULE_VERSION:
            raise ValueError("PROTOCOL_CALENDAR_VERSION")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("PROTOCOL_DUPLICATE_SYMBOL")
        if any(len(s) != 6 or not s.isascii() or not s.isdigit()
               or not s.startswith(("60", "68", "00", "30")) for s in self.symbols):
            raise ValueError("PROTOCOL_STOCK_SYMBOL")
        return self


def planning_start(session: date) -> datetime:
    return datetime.combine(session - timedelta(days=1), time(), SH)


def maturity(session: date) -> datetime:
    return datetime.combine(session, time(15, 30), SH)


def deadline(session: date) -> datetime:
    # A fixed three-calendar-day grace window, not selected by outcome.
    return datetime.combine(session + timedelta(days=3), time(23, 59, 59), SH)


def protocol_sha256(protocol: CohortProtocol) -> str:
    payload = json.dumps(protocol.model_dump(mode="json"), sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class CohortBatchRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    protocol_sha256: str = Field(pattern=SHA)
    frozen_at: AwareDatetime
    input_end: date
    freeze_receipt_sha256: str = Field(pattern=SHA)
    outcome_observed_at: AwareDatetime | None = None
    outcome_receipt_sha256: str | None = Field(default=None, pattern=SHA)
    batch: DailyAssessmentBatch

    @model_validator(mode="after")
    def validate_record(self) -> CohortBatchRecord:
        session = self.batch.session
        if not planning_start(session) <= self.frozen_at < datetime.combine(session, time(), SH):
            raise ValueError("PROTOCOL_FREEZE_WINDOW")
        if self.input_end != session - timedelta(days=2):
            raise ValueError("PROTOCOL_INPUT_END")
        pending = all(row.outcome_status == "PENDING" for row in self.batch.rows)
        if pending:
            if self.outcome_observed_at is not None or self.outcome_receipt_sha256 is not None:
                raise ValueError("PROTOCOL_PENDING_HAS_OUTCOME")
        elif (self.outcome_observed_at is None or self.outcome_receipt_sha256 is None
              or not maturity(session) <= self.outcome_observed_at <= deadline(session)):
            raise ValueError("PROTOCOL_OUTCOME_TIME_OR_HASH")
        return self


def assess_registered_cohort(protocol: CohortProtocol, records: tuple[CohortBatchRecord, ...], *,
                             expected_protocol_sha256: str, now: datetime) -> dict:
    """Use the immutable interval, never a caller-selected favorable subinterval."""
    protocol = CohortProtocol.model_validate(protocol.model_dump())
    digest = protocol_sha256(protocol)
    if digest != expected_protocol_sha256:
        raise ValueError("PROTOCOL_EXTERNAL_HASH_MISMATCH")
    if now.utcoffset() is None or now < protocol.registered_at:
        raise ValueError("PROTOCOL_ASSESSMENT_CLOCK")
    sessions = protocol.sessions()
    seen = set()
    matured = tuple(d for d in sessions if maturity(d) <= now)
    matured_records = []
    for raw in records:
        record = CohortBatchRecord.model_validate(raw.model_dump())
        batch = record.batch
        if batch.session not in sessions or batch.session in seen:
            raise ValueError("PROTOCOL_DUPLICATE_OR_OUT_OF_RANGE_SESSION")
        seen.add(batch.session)
        if record.protocol_sha256 != digest:
            raise ValueError("PROTOCOL_RECORD_HASH_MISMATCH")
        if tuple(row.subject_id for row in batch.rows) != protocol.symbols:
            raise ValueError("PROTOCOL_FIXED_COHORT_MISMATCH")
        if record.frozen_at > now or (record.outcome_observed_at and record.outcome_observed_at > now):
            raise ValueError("PROTOCOL_RECORD_NOT_YET_OBSERVED")
        if batch.session in matured:
            matured_records.append(batch)
    report = (assess_daily_cohort(protocol.first, matured[-1], protocol.symbols,
                                  tuple(matured_records), now=now) if matured else None)
    return {
        "status": "PREREGISTERED_CONTENT_DESCRIPTIVE_ONLY",
        "protocol_sha256": digest,
        "fixed_first": protocol.first.isoformat(),
        "fixed_last": protocol.last.isoformat(),
        "expected_sessions_full_interval": len(sessions),
        "expected_slots_full_interval": len(sessions) * len(protocol.symbols),
        "matured_sessions": len(matured),
        "future_sessions": len(sessions) - len(matured),
        "future_sessions_with_frozen_batch": sum(d in seen for d in sessions if d not in matured),
        "assessment": report,
        "final_interval_matured": len(matured) == len(sessions),
        "interval_preregistration_verified": False,
        "external_commit_first_attempt_and_source_completeness_verification_required": True,
        "probability_calibrated": False,
        "model_promotion_allowed": False,
        "research_only": True,
        "execution_allowed": False,
    }
