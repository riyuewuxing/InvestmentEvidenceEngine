from datetime import UTC, datetime
from pathlib import Path

import pytest

from investment_evidence_engine.prediction_observation_view import project_prediction_observations

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot-receipts"
PROTOCOL = ROOT / "pilot-protocols/public-daily-20261130-v1.json"
NOW = datetime(2026, 11, 27, 14, tzinfo=UTC)


def data():
    return [(PILOT / f"public-control-20261127-{name}.json").read_bytes()
            for name in ("frozen", "outcome", "assessment")] + [PROTOCOL.read_bytes()]


def test_actual_pinned_retained_receipts_are_descriptive_only():
    out = project_prediction_observations(*data(), now=NOW)
    p, c = out["pilot"], out["cohort"]
    assert p["status"] == "RETAINED_TERMINAL"
    assert p["direction"] == "UP" and p["outcome_status"] == "UNAVAILABLE"
    assert p["selected_count"] == 1 and p["evaluable_count"] == 0
    assert p["accuracy"] is None and p["flat_accuracy"] is None
    assert p["accuracy_bounds"] == [0., 1.]
    assert not p["retry_authorized"] and not p["first_attempt_provenance_reverified_at_runtime"]
    assert c["status"] == "PREREGISTERED_NOT_STARTED"
    assert (c["expected_sessions"], c["expected_slots"], c["evaluable_count"]) == (20, 40, 0)
    assert out["model_validation_status"] == "NOT_VALIDATED"
    assert not out["private_event_chain_verified"] and not out["execution_allowed"]


def test_after_planning_starts_unknown_receipt_index_is_not_zero():
    out = project_prediction_observations(*data(), now=datetime(2026, 11, 28, 16, tzinfo=UTC))
    assert out["cohort"]["status"] == "REGISTERED_RECEIPTS_NOT_CHECKED"
    assert out["cohort"]["evaluable_count"] is None
    assert not out["cohort"]["activation_authorized"]


@pytest.mark.parametrize("index", range(4))
def test_tampered_or_missing_receipts_fail_closed_independently(index):
    for invalid in (b'{"x":1,"x":2}', b'{}', None):
        rows = data()
        rows[index] = invalid
        out = project_prediction_observations(*rows, now=NOW)
        bad, good = ("cohort", "pilot") if index == 3 else ("pilot", "cohort")
        assert out[bad]["status"] == ("UNAVAILABLE" if invalid is None else "INVALID")
        assert out[good]["status"] in {"RETAINED_TERMINAL", "PREREGISTERED_NOT_STARTED"}


def test_future_outcome_is_not_visible_and_naive_clock_is_rejected():
    rows = data()
    out = project_prediction_observations(*rows, now=datetime(2026, 11, 27, 7, tzinfo=UTC))
    assert out["pilot"]["status"] == "INVALID"
    with pytest.raises(ValueError):
        project_prediction_observations(*rows, now=datetime(2026, 11, 27))
