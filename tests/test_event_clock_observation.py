import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from investment_evidence_engine.event_clock_observation import parse_public_event_observation

FILE = Path(__file__).resolve().parents[1] / "controls/event-clock-202511-202512-retrospective.json"
NOW = datetime(2026, 11, 27, 12, tzinfo=UTC)


def test_actual_public_clock_and_opposite_retrospective_responses():
    rows = parse_public_event_observation(FILE.read_bytes(), now=NOW)
    assert [x["event_session"] for x in rows] == ["2025-09-18", "2025-12-11"]
    assert [x["observed_price_sign"] for x in rows] == ["NEGATIVE", "POSITIVE"]
    assert [x["shanghai_release_at"][11:16] for x in rows] == ["02:00", "03:00"]
    assert all(x["declared_before_premarket"] for x in rows)
    assert all(x["actual_receipt_at_premarket"] == "AFTER_CUTOFF" for x in rows)
    assert all(x["actual_receipt_at_auction"] == "AFTER_CUTOFF" for x in rows)
    assert all(x["actual_receipt_at_retrieval"] == "RECORDED_CHRONOLOGY_ONLY" for x in rows)
    assert rows[1]["windows"][-1]["listed_benchmark_ex_date_in_window"]
    assert all(not x["formal_admission"] and not x["causal_effect_estimated"] for x in rows)


def test_tampered_event_scope_or_retrieval_does_not_admit():
    a = json.loads(FILE.read_bytes())
    a["formal_admission"] = True
    with pytest.raises(ValueError):
        parse_public_event_observation(json.dumps(a).encode(), now=NOW)
    with pytest.raises(ValueError):
        parse_public_event_observation(FILE.read_bytes(), now=datetime(2025, 12, 11, tzinfo=UTC))
    a = json.loads(FILE.read_bytes())
    a["log_lines"][0] = a["log_lines"][0].replace("d16da9e30", "a16da9e30")
    with pytest.raises(ValueError):
        parse_public_event_observation(json.dumps(a).encode(), now=NOW)
