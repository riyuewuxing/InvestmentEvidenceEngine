import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from investment_evidence_engine.prospective_assessment import DailyAssessmentBatch, DailyAssessmentRow
from investment_evidence_engine.prospective_protocol import (
    CohortBatchRecord,
    CohortProtocol,
    assess_registered_cohort,
    maturity,
    planning_start,
    protocol_sha256,
)

PATH = Path(__file__).resolve().parents[1] / "pilot-protocols/public-daily-20261130-v1.json"


def protocol():
    return CohortProtocol.model_validate_json(PATH.read_text(encoding="utf-8"))


def record(p, session, *, outcome=True):
    rows = tuple(DailyAssessmentRow(
        subject_id=s, disposition="SELECTED", direction="UP",
        outcome_status="OBSERVED" if outcome else "PENDING",
        observed_return=0.02 if outcome else None,
    ) for s in p.symbols)
    return CohortBatchRecord(
        protocol_sha256=protocol_sha256(p), frozen_at=planning_start(session)+timedelta(hours=8),
        input_end=session-timedelta(days=2), freeze_receipt_sha256="1"*64,
        outcome_observed_at=maturity(session) if outcome else None,
        outcome_receipt_sha256="2"*64 if outcome else None,
        batch=DailyAssessmentBatch(session=session, rows=rows),
    )


def test_exact_calendar_and_pre_maturity():
    p = protocol()
    assert len(p.sessions()) == 20
    assert p.sessions()[0] == date(2026, 11, 30)
    assert p.sessions()[-1] == date(2026, 12, 25)
    r = assess_registered_cohort(p, (), expected_protocol_sha256=protocol_sha256(p),
                                 now=datetime(2026, 11, 26, 7, tzinfo=UTC))
    assert r["expected_slots_full_interval"] == 40
    assert r["future_sessions"] == 20
    assert r["assessment"] is None
    assert not r["interval_preregistration_verified"]


def test_no_cherry_picked_range_and_missing_day():
    p = protocol()
    first, second, *_ = p.sessions()
    r = assess_registered_cohort(p, (record(p, second),), expected_protocol_sha256=protocol_sha256(p),
                                 now=maturity(second))
    assert r["matured_sessions"] == 2
    assert r["assessment"]["missing_sessions"] == [first.isoformat()]
    assert r["assessment"]["expected_subject_session_slots"] == 4
    assert r["assessment"]["full_scheduled_evaluable_coverage"] == 0.5
    assert r["future_sessions"] == 18


def test_pending_freeze_before_maturity_not_counted_as_result():
    p = protocol()
    f = record(p, p.first, outcome=False)
    result = assess_registered_cohort(p, (f,), expected_protocol_sha256=protocol_sha256(p), now=f.frozen_at)
    assert result["future_sessions_with_frozen_batch"] == 1
    assert result["assessment"] is None


def test_late_registration_and_altered_hash():
    p = protocol()
    raw = json.loads(PATH.read_text(encoding="utf-8"))
    raw["registered_at"] = planning_start(p.first).isoformat()
    with pytest.raises(ValueError):
        CohortProtocol.model_validate_json(json.dumps(raw))
    with pytest.raises(ValueError):
        assess_registered_cohort(p, (), expected_protocol_sha256="0"*64, now=p.registered_at)


def test_reject_late_freeze_wrong_cutoff_and_duplicates():
    p = protocol()
    f = record(p, p.first)
    for change in ({"frozen_at": maturity(p.first)}, {"input_end": p.first},
                   {"outcome_observed_at": maturity(p.first)-timedelta(seconds=1)}):
        with pytest.raises(ValueError):
            CohortBatchRecord.model_validate({**f.model_dump(), **change})
    with pytest.raises(ValueError):
        assess_registered_cohort(p, (f, f), expected_protocol_sha256=protocol_sha256(p), now=maturity(p.first))


def test_reject_reordered_cohort():
    p = protocol()
    f = record(p, p.first)
    altered = f.model_copy(update={"batch": f.batch.model_copy(update={"rows": tuple(reversed(f.batch.rows))})})
    with pytest.raises(ValueError):
        assess_registered_cohort(p, (altered,), expected_protocol_sha256=protocol_sha256(p), now=maturity(p.first))
