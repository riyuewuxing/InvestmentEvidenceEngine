import json
from datetime import UTC, date, datetime
from pathlib import Path

from investment_evidence_engine.prospective_assessment import (
    DailyAssessmentBatch,
    DailyAssessmentRow,
)
from investment_evidence_engine.prospective_diagnostics import assess_paired_direction_delta
from investment_evidence_engine.public_prediction_pilot import SYMBOL, TARGET
from investment_evidence_engine.public_prediction_settlement import (
    FROZEN_PUBLIC_SHA256,
    assess,
    load_pinned_freeze,
)

NOW = datetime(2026, 11, 28, tzinfo=UTC)
FIRST, LAST = date(2026, 11, 23), date(2026, 11, 25)
SYMBOLS = ("000001", "000002")
ROOT = Path(__file__).resolve().parents[1]


def row(symbol, prediction, actual=None, *, disposition="SELECTED"):
    return DailyAssessmentRow(
        subject_id=symbol, disposition=disposition, direction=prediction,
        outcome_status="OBSERVED" if actual is not None else "UNAVAILABLE",
        observed_return=actual,
    )


def batch(day, *rows):
    return DailyAssessmentBatch(session=date(2026, 11, day), rows=rows)


def test_paired_missingness_bounds_keep_flat_control_shared():
    result = assess_paired_direction_delta(
        FIRST, LAST, SYMBOLS,
        (
            batch(23, row(SYMBOLS[0], "UP", .02), row(SYMBOLS[1], "DOWN", 0.)),
            batch(24, row(SYMBOLS[0], "UP"), row(SYMBOLS[1], "FLAT")),
        ),
        now=NOW,
    )
    assert result["observed_paired_accuracy_delta"] == 0
    assert result["selected_paired_accuracy_delta_bounds"] == [-.25, .25]
    assert result["selected_slots"] == 4
    assert result["observed_selected_slots"] == 2
    assert result["unfrozen_slots_not_scored"] == 2
    assert result["full_scheduled_evaluable_coverage"] == 1 / 3
    assert not result["confidence_interval_estimated"]
    assert not result["model_promotion_allowed"]


def test_no_selection_is_not_zero_delta():
    result = assess_paired_direction_delta(
        FIRST, LAST, SYMBOLS, (), now=NOW,
    )
    assert result["selected_paired_accuracy_delta_bounds"] is None
    assert result["observed_paired_accuracy_delta"] is None


def test_identical_flat_forecast_missing_label_does_not_invent_accuracy():
    result = assess_paired_direction_delta(
        FIRST, FIRST, SYMBOLS,
        (batch(23, row(SYMBOLS[0], "FLAT"),
               row(SYMBOLS[1], None, disposition="UNAVAILABLE")),),
        now=NOW,
    )
    assert result["selected_paired_accuracy_delta_bounds"] == [0, 0]
    assert result["observed_paired_accuracy_delta"] is None
    assert result["observed_selected_slots"] == 0


def test_actual_archived_pilot_is_unavailable_not_an_incorrect_forecast():
    frozen = load_pinned_freeze()
    outcome = json.loads((ROOT / "pilot-receipts/public-control-20261127-outcome.json").read_text())
    original = assess(
        frozen, outcome, expected_freeze_sha256=FROZEN_PUBLIC_SHA256,
        expected_outcome_sha256="f25ec3d05cb8784583518a1c49f2a2152202fe25c439dd46b67cbcdbe43d8415",
        now=NOW,
    )
    assert original["assessment"]["observed_selected_accuracy"] is None
    assert outcome["status"] == "UNAVAILABLE" and outcome["rows"] == []
    r = assess_paired_direction_delta(
        TARGET, TARGET, (SYMBOL,),
        (DailyAssessmentBatch(session=TARGET, rows=(
            row(SYMBOL, frozen["direction"]),
        )),),
        now=NOW,
    )
    assert r["selected_paired_accuracy_delta_bounds"] == [-1, 1]
    assert r["observed_paired_accuracy_delta"] is None
    assert not r["model_promotion_allowed"]
