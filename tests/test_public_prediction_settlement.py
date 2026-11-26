from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from investment_evidence_engine.public_prediction_pilot import (
    SYMBOL,
    TARGET,
    calendar_rows_expected,
    freeze,
    input_sessions,
    sha256,
)
from investment_evidence_engine.public_prediction_settlement import (
    DEADLINE,
    FROZEN_PUBLIC_SHA256,
    MATURITY,
    assess,
    load_pinned_freeze,
    outcome_observation,
    verify_outcome,
)

CLOCK = datetime(2026, 11, 26, 6, 0, tzinfo=UTC)


def frozen():
    rows = [[day, "sh." + SYMBOL, "10", "11", "100", "3", "1"] for day in input_sessions()]
    return freeze(calendar_rows_expected(), rows, started=CLOCK, observed=CLOCK)


def row(close="11", status="1"):
    return [TARGET.isoformat(), "sh." + SYMBOL, "10", close, "100", "3", status]


def observe(rows):
    return outcome_observation(rows, started=MATURITY, observed=MATURITY)


@pytest.mark.parametrize(("rows", "status", "accuracy"), [
    ([row()], "OBSERVED", 1.0),
    ([row("9")], "OBSERVED", 0.0),
    ([], "UNAVAILABLE", None),
    ([row(status="0")], "UNTRADEABLE", None),
])
def test_settlement_and_coverage(rows, status, accuracy):
    f, o = frozen(), observe(rows)
    verify_outcome(o)
    assert o["status"] == status
    result = assess(f, o, expected_freeze_sha256=sha256(f),
                    expected_outcome_sha256=sha256(o), now=MATURITY)
    a = result["assessment"]
    assert a["observed_selected_accuracy"] == accuracy
    assert a["expected_subject_session_slots"] == 1
    assert a["full_scheduled_evaluable_coverage"] == (0 if accuracy is None else 1)
    assert not result["model_promotion_allowed"]


def test_refuse_early_late_duplicate_or_wrong_identity():
    for t in (MATURITY - timedelta(seconds=1), DEADLINE + timedelta(seconds=1)):
        with pytest.raises(ValueError):
            outcome_observation([row()], started=t, observed=t)
    with pytest.raises(ValueError):
        observe([row(), row()])
    wrong = row()
    wrong[0] = "2026-11-26"
    with pytest.raises(ValueError):
        observe([wrong])


def test_refuse_tampering_and_wrong_external_pin():
    f, o = frozen(), observe([row()])
    changed = deepcopy(o)
    changed["raw_intraday_return"] = "0.9"
    with pytest.raises(ValueError):
        verify_outcome(changed)
    with pytest.raises(ValueError):
        assess(f, o, expected_freeze_sha256="0"*64, expected_outcome_sha256=sha256(o), now=MATURITY)
    with pytest.raises(ValueError):
        assess(f, o, expected_freeze_sha256=sha256(f), expected_outcome_sha256=sha256(o),
               now=MATURITY - timedelta(seconds=1))


def test_actual_frozen_public_receipt_pin_and_tamper(tmp_path):
    f = load_pinned_freeze()
    assert sha256(f) == FROZEN_PUBLIC_SHA256
    assert f["direction"] == "UP"
    path = tmp_path / "wrong.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="PINNED_FREEZE_BYTES_MISMATCH"):
        load_pinned_freeze(path)
    # Hypothetical outcome strictly for contract testing, never a real outcome.
    o = observe([row("9")])
    report = assess(f, o, expected_freeze_sha256=FROZEN_PUBLIC_SHA256,
                    expected_outcome_sha256=sha256(o), now=MATURITY)
    assert report["assessment"]["observed_selected_accuracy"] == 0
    assert report["first_run_provenance_verification_by_caller_required"]
