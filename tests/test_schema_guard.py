import pandas as pd

from investment_evidence_engine.schema_guard import (
    compare_schema_fingerprint,
    inspect_frame_schema,
    inspect_normalized_ohlcv,
)


def test_ohlcv_schema_passes() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-09-01"]),
            "open": [1.0],
            "high": [1.1],
            "low": [0.9],
            "close": [1.05],
            "volume": [100.0],
            "amount": [105.0],
        }
    )
    check = inspect_normalized_ohlcv(frame)
    assert check.status == "PASS"
    assert not check.missing_required


def test_missing_required_column_blocks() -> None:
    frame = pd.DataFrame({"date": ["2026-09-01"], "close": [1.0]})
    check = inspect_normalized_ohlcv(frame)
    assert check.status == "BLOCK"
    assert "open" in check.missing_required


def test_unexpected_column_warns() -> None:
    frame = pd.DataFrame(
        {
            "date": [1],
            "open": [1],
            "high": [1],
            "low": [1],
            "close": [1],
            "volume": [1],
            "mystery": [1],
        }
    )
    check = inspect_normalized_ohlcv(frame)
    assert check.status == "WARN"
    assert check.unexpected_columns == ("mystery",)


def test_schema_fingerprint_drift_warns() -> None:
    frame = pd.DataFrame({"a": [1], "b": [2]})
    observed = inspect_frame_schema(frame)
    result = compare_schema_fingerprint(observed, "0" * 64)
    assert result["status"] == "WARN"
    assert result["drift"] is True
