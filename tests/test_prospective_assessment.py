from datetime import date, datetime, timezone

import pytest

from investment_evidence_engine.prospective_assessment import (
    DailyAssessmentBatch,
    DailyAssessmentRow,
    assess_daily_cohort,
)

NOW = datetime(2026,11,26,8,tzinfo=timezone.utc)
A,B = "600000","510050"
FIRST,LAST = date(2026,11,23),date(2026,11,25)


def row(subject, direction="UP", outcome="OBSERVED", value=0.01):
    return DailyAssessmentRow(subject_id=subject,disposition="SELECTED",direction=direction,
                              outcome_status=outcome,observed_return=value)


def batch(day,*rows):
    return DailyAssessmentBatch(session=date(2026,11,day),rows=rows)


def test_fixed_coverage_missing_and_paired_days():
    first = batch(23,row(A),row(B,"DOWN","OBSERVED",0.01))
    second = batch(24,row(A,"FLAT","OBSERVED",0.001),row(B,"UP","UNAVAILABLE",None))
    r = assess_daily_cohort(FIRST,LAST,(A,B),(first,second),now=NOW)
    assert r["expected_sessions"] == 3 and r["missing_sessions"] == ["2026-11-25"]
    assert r["unfrozen_slots"] == 2 and r["full_scheduled_evaluable_coverage"] == 0.5
    assert r["observed_selected_accuracy"] == 2/3
    assert r["observed_selected_flat_accuracy"] == 1/3
    assert r["selected_accuracy_bounds_from_missing_outcomes"] == [0.5,0.75]
    assert r["complete_paired_session_count"] == 1
    assert r["complete_session_mean_accuracy_difference"] == 0.5
    assert r["confusion_predicted_by_actual"]["DOWN"]["UP"] == 1
    assert not r["probability_calibrated"] and not r["execution_allowed"]


def test_no_frozen_never_claims_zero_accuracy():
    r = assess_daily_cohort(FIRST,LAST,(A,B),(),now=NOW)
    assert r["observed_selected_accuracy"] is None
    assert r["selected_accuracy_bounds_from_missing_outcomes"] is None
    assert r["full_scheduled_evaluable_coverage"] == 0
    assert r["complete_paired_session_count"] == 0


def test_reject_cherrypicked_duplicate_or_reordered_cohort():
    a = batch(23,row(A),row(B))
    with pytest.raises(ValueError,match="DUPLICATE"):
        assess_daily_cohort(FIRST,LAST,(A,B),(a,a),now=NOW)
    with pytest.raises(ValueError,match="COHORT_MISMATCH"):
        assess_daily_cohort(FIRST,LAST,(A,B),(batch(23,row(B),row(A)),),now=NOW)
    with pytest.raises(ValueError,match="UNSCHEDULED"):
        assess_daily_cohort(FIRST,LAST,(A,B),(batch(22,row(A),row(B)),),now=NOW)
    with pytest.raises(ValueError,match="HORIZON_NOT_MATURED"):
        assess_daily_cohort(FIRST,date(2026,11,27),(A,B),(),now=NOW)


def test_pending_and_missing_never_become_returns():
    a = batch(23,row(A,outcome="PENDING",value=None),row(B,outcome="PENDING",value=None))
    r = assess_daily_cohort(FIRST,LAST,(A,B),(a,),now=NOW)
    assert r["selected_accuracy_bounds_from_missing_outcomes"] == [0,1]
    assert r["outcome_counts"]["PENDING"] == 2
    with pytest.raises(ValueError,match="OUTCOME_MISMATCH"):
        row(A,outcome="UNAVAILABLE",value=0.)
    with pytest.raises(ValueError,match="PARTIAL_FINALIZATION"):
        batch(23,row(A),row(B,outcome="PENDING",value=None))
