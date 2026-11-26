from datetime import UTC, date, datetime, timedelta

import pytest

from investment_evidence_engine.historical_capture import PublicSecurity
from investment_evidence_engine.historical_receipt import (
    HistoricalReceipt,
    load_receipt,
    persist_receipt,
)
from investment_evidence_engine.historical_reference import DailyClose, HistoricalCloseSeries

A = PublicSecurity(symbol="600519", asset_type="STOCK")
B = PublicSecurity(symbol="510050", asset_type="ETF")
END = date(2026, 11, 25)
START = END - timedelta(days=40)
NOW = datetime(2026, 11, 26, 5, tzinfo=UTC)


def series(subject, provider, scale):
    days = [START+timedelta(days=i) for i in range(41) if (START+timedelta(days=i)).weekday()<5]
    return HistoricalCloseSeries(subject_id=subject.symbol, currency="CNY", price_basis="RAW_CLOSE",
        source_label=provider, closes=tuple(DailyClose(session=d, close=float(scale*(100+i))) for i,d in enumerate(days)))


def receipt(*extra):
    return HistoricalReceipt(candidate=A, alternative=B, first_requested=START, last_completed=END,
        observed_at=NOW-timedelta(minutes=1), akshare_version="synthetic",
        series=(series(A,"baostock",1),series(B,"sina",2),*extra))


def test_normalized_receipt_exact_bytes_and_recomputed_result(tmp_path):
    digest, result = persist_receipt(tmp_path, receipt())
    assert result["status"] == "OBSERVED_REFERENCE_ONLY"
    loaded = load_receipt(tmp_path,A,B,END,now=NOW)
    assert loaded["normalized_observation_sha256"] == digest and loaded["normalized_observation_rehashed"]
    assert loaded["reference"] == result["reference"]
    assert not loaded["reference"]["decision_authority"]
    assert persist_receipt(tmp_path,receipt())[0] == digest
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_conflict_recomputed_no_numeric_output(tmp_path):
    _, result = persist_receipt(tmp_path,receipt(series(A,"sina",2)))
    assert result["status"] == "BLOCKED" and result["error_code"] == "SOURCE_CONFLICT"
    loaded = load_receipt(tmp_path,A,B,END,now=NOW)
    assert "reference" not in loaded


def test_tamper_and_identity_fail_closed(tmp_path):
    persist_receipt(tmp_path,receipt())
    wrong = PublicSecurity(symbol="510300", asset_type="ETF")
    with pytest.raises(ValueError):
        load_receipt(tmp_path,A,wrong,END,now=NOW)
    with pytest.raises(ValueError):
        load_receipt(tmp_path,A,B,END-timedelta(days=1),now=NOW)
    path = next(tmp_path.glob("*.json"))
    path.write_bytes(path.read_bytes()+b" ")
    with pytest.raises(ValueError):
        load_receipt(tmp_path,A,B,END,now=NOW)


def test_future_observation_and_older_fallback_rejected(tmp_path):
    persist_receipt(tmp_path, receipt())
    newer = receipt().model_copy(update={"observed_at": NOW+timedelta(minutes=1)})
    persist_receipt(tmp_path,newer)
    with pytest.raises(ValueError):
        load_receipt(tmp_path,A,B,END,now=NOW)


def test_latest_conflict_does_not_fall_back_to_old_success(tmp_path):
    persist_receipt(tmp_path,receipt())
    conflict = receipt(series(A,"sina",2)).model_copy(update={"observed_at": NOW})
    persist_receipt(tmp_path,conflict)
    assert load_receipt(tmp_path,A,B,END,now=NOW)["error_code"] == "SOURCE_CONFLICT"
