from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from investment_evidence_engine.cohort_progress import describe_cohort_progress
from investment_evidence_engine.prospective_assessment import (
    DailyAssessmentBatch,
    DailyAssessmentRow,
)
from investment_evidence_engine.prospective_protocol import (
    CohortBatchRecord,
    CohortProtocol,
    deadline,
    maturity,
    planning_start,
    protocol_sha256,
)

DAY = date(2026, 12, 1)
PROTOCOL = CohortProtocol(
    protocol_id="synthetic_progress_test",
    registered_at=planning_start(DAY) - timedelta(days=1),
    first=DAY,
    last=DAY,
    symbols=("000001", "000002"),
    strategy="daily_intraday_persistence_5",
    strategy_version="1.0",
    threshold="0.001",
    benchmark="FLAT",
    label="RAW_OPEN_TO_CLOSE_GROSS_NOT_EXECUTABLE_TRADE",
    planning_rule="PREVIOUS_CALENDAR_DAY_EXCLUDE_PLANNING_DAY",
    source="baostock_unadjusted_daily",
    calendar_version="SSE_SZSE_2025_2026_ANNUAL_NOTICES_V1",
    first_attempt_only=True,
    no_backfill=True,
    research_only=True,
    execution_allowed=False,
)
DIGEST = protocol_sha256(PROTOCOL)


def record(statuses=("PENDING", "PENDING"), outcome_hash="b" * 64):
    pending = statuses == ("PENDING", "PENDING")
    return CohortBatchRecord(
        protocol_sha256=DIGEST,
        frozen_at=planning_start(DAY),
        input_end=DAY - timedelta(days=2),
        freeze_receipt_sha256="a" * 64,
        outcome_observed_at=None if pending else maturity(DAY),
        outcome_receipt_sha256=None if pending else outcome_hash,
        batch=DailyAssessmentBatch(
            session=DAY,
            rows=tuple(
                DailyAssessmentRow(
                    subject_id=symbol,
                    disposition="SELECTED",
                    direction="UP",
                    outcome_status=status,
                    observed_return=0.01 if status == "OBSERVED" else None,
                )
                for symbol, status in zip(PROTOCOL.symbols, statuses, strict=True)
            ),
        ),
    )


def report(now, records=()):
    return describe_cohort_progress(PROTOCOL, records, expected_protocol_sha256=DIGEST, now=now)


@pytest.mark.parametrize(("now", "state"), [
    (planning_start(DAY) - timedelta(seconds=1), "WAITING_FOR_PLANNING"),
    (planning_start(DAY), "PLANNING_WINDOW_OPEN_NO_RECEIPT"),
    (planning_start(DAY) + timedelta(days=1), "FREEZE_WINDOW_CLOSED_NO_RECEIPT"),
])
def test_no_receipt_never_inferred_as_attempt_or_prediction(now: datetime, state: str):
    result = report(now)
    row = result["sessions"][0]
    assert row["state"] == state
    assert row["selected"] is None and row["evaluable"] is None
    assert not result["activation_authorized"]
    assert not result["first_attempt_provenance_verified"]


@pytest.mark.parametrize(("now", "state"), [
    (maturity(DAY) - timedelta(seconds=1), "WAITING_FOR_OBSERVATION"),
    (maturity(DAY), "SETTLEMENT_WINDOW_OPEN_NO_RECEIPT"),
    (deadline(DAY), "SETTLEMENT_WINDOW_OPEN_NO_RECEIPT"),
    (deadline(DAY) + timedelta(seconds=1), "SETTLEMENT_WINDOW_CLOSED_NO_RECEIPT"),
])
def test_frozen_pending_windows_are_inclusive_only_as_registered(now: datetime, state: str):
    result = report(now, (record(),))
    assert result["sessions"][0]["state"] == state
    assert result["sessions"][0]["evaluable"] == 0
    assert not result["retry_authorized"] and not result["backfill_authorized"]
    assert result["model_validation_status"] == "NOT_VALIDATED"


@pytest.mark.parametrize(("statuses", "state", "evaluable"), [
    (("UNAVAILABLE", "UNTRADEABLE"), "TERMINAL_UNEVALUABLE", 0),
    (("OBSERVED", "UNAVAILABLE"), "TERMINAL_PARTIAL", 1),
    (("OBSERVED", "OBSERVED"), "TERMINAL_COMPLETE_PAIRED", 2),
])
def test_final_observation_including_missing_never_reopens(statuses, state, evaluable):
    result = report(maturity(DAY), (record(statuses),))
    row = result["sessions"][0]
    assert row["state"] == state and row["evaluable"] == evaluable
    assert not result["retry_authorized"]
    assert not result["probability_calibrated"]
    assert result["assessment"]["assessment"]["observed_selected_accuracy"] == (1 if evaluable else None)


def test_expired_interval_not_promoted_and_reused_receipt_blocked():
    now = deadline(DAY) + timedelta(seconds=1)
    result = report(now)
    assert result["status"] == "INTERVAL_CLOSED_DESCRIPTIVE_ONLY"
    assert result["model_validation_status"] == "NOT_VALIDATED"
    with pytest.raises(ValueError, match="RECEIPT_REUSE"):
        report(now, (record(("OBSERVED", "OBSERVED"), outcome_hash="a" * 64),))


def test_actual_registered_protocol_is_not_started_at_r07_boundary():
    path = Path(__file__).resolve().parents[1] / "pilot-protocols/public-daily-20261130-v1.json"
    protocol = CohortProtocol.model_validate_json(path.read_text(encoding="utf-8"))
    result = describe_cohort_progress(
        protocol, (),
        expected_protocol_sha256="d845cf330f008695e0dd220aa09118ed62e3952dc7238ab20110c7c4e732f0f0",
        now=datetime(2026, 11, 27, 12, 7, tzinfo=UTC),
    )
    assert result["status"] == "WAITING_FOR_OBSERVATION"
    assert len(result["sessions"]) == 20
    assert all(row["state"] == "WAITING_FOR_PLANNING" for row in result["sessions"])
    assert result["assessment"]["expected_slots_full_interval"] == 40
    assert result["assessment"]["matured_sessions"] == 0
    assert result["paired_direction_diagnostics"] is None
    assert not result["activation_authorized"]
