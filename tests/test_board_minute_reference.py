from datetime import datetime

from investment_evidence_engine.board_minute_reference import board_minute_reference

NOW = datetime.fromisoformat("2026-11-27T14:45:00+08:00")


def test_board_latest_observed_day_and_future_rejection():
    rows = [
        {"time": "2026-11-26 15:00", "close": 100.0},
        {"time": "2026-11-27 14:30", "close": 101.0},
        {"time": "2026-11-27 14:40", "close": 102.0},
        {"time": "2026-11-27 14:46", "close": 103.0},
        {"time": "2026-11-27 09:25", "close": 104.0},
        {"time": "2026-11-27 12:15", "close": 105.0},
    ]
    result = board_minute_reference(rows, checked_at=NOW)
    assert result["status"] == "SAME_DATE_VENDOR_REFERENCE"
    assert result["session_date"] == "2026-11-27"
    assert [x["close"] for x in result["items"]] == [101.0, 102.0]
    assert result["rejected_count"] == 3
    assert result["formal_pit"] is False and result["decision_authority"] is False


def test_board_historical_and_conflicting_duplicates():
    row = {"time": "2026-11-26 15:00", "close": 100.0}
    assert board_minute_reference([row, row], checked_at=NOW)["status"] == "HISTORICAL_VENDOR_REFERENCE"
    result = board_minute_reference([row, dict(row, close=200.0)], checked_at=NOW)
    assert result["status"] == "CONFLICTING_DUPLICATES" and result["items"] == []
    assert board_minute_reference([], checked_at=NOW)["status"] == "UNAVAILABLE"
