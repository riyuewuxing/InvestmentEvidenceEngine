from datetime import UTC, date, datetime, timedelta

import pytest

from investment_evidence_engine.historical_capture import PublicSecurity
from investment_evidence_engine.historical_receipt import (
    HistoricalCaptureFailure,
    HistoricalReceipt,
    load_receipt,
    persist_receipt,
)
from investment_evidence_engine.historical_reference import DailyClose, HistoricalCloseSeries
from investment_evidence_engine.holding_risk import (
    ShareCashDistribution,
    ShareCashDistributionInputs,
)
from investment_evidence_engine.market_calendar import CalendarObservation, scheduled_days

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
    observed = (series(A,"baostock",1),series(B,"sina",2),*extra)
    failures = () if extra else (HistoricalCaptureFailure(provider="sina", asset_type="STOCK",
                                                          error_code="SYNTHETIC_UNAVAILABLE"),)
    return HistoricalReceipt(candidate=A, alternative=B, first_requested=START, last_completed=END,
        observed_at=NOW-timedelta(minutes=1), akshare_version="synthetic",
        attempted_providers=("sina", "baostock"), failures=failures, series=observed)


def test_normalized_receipt_exact_bytes_and_recomputed_result(tmp_path):
    digest, result = persist_receipt(tmp_path, receipt())
    assert result["status"] == "OBSERVED_REFERENCE_ONLY"
    loaded = load_receipt(tmp_path,A,B,END,now=NOW)
    assert loaded["normalized_observation_sha256"] == digest and loaded["normalized_observation_rehashed"]
    assert loaded["reference"] == result["reference"]
    assert loaded["failures"] == [{"provider":"sina", "asset_type":"STOCK", "error_code":"SYNTHETIC_UNAVAILABLE"}]
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


def test_missing_or_double_counted_provider_attempt_rejected(tmp_path):
    good = receipt()
    with pytest.raises(ValueError):
        persist_receipt(tmp_path, good.model_copy(update={"failures": ()}))
    with pytest.raises(ValueError):
        persist_receipt(tmp_path, good.model_copy(update={"failures": good.failures + good.failures}))
    with pytest.raises(ValueError):
        persist_receipt(tmp_path, good.model_copy(update={"attempted_providers": ("sina", "baostock", "tencent")}))


def test_v1_canonical_encoding_is_unchanged(tmp_path):
    import hashlib
    import json
    original=receipt()
    payload=original.model_dump(mode="json")
    for name in ("calendar","calendar_error_code","distributions","share_cash_distributions"):
        payload.pop(name)
    old_bytes=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    digest, result=persist_receipt(tmp_path,original)
    assert digest==hashlib.sha256(old_bytes).hexdigest()
    assert (tmp_path/(digest+".json")).read_bytes()==old_bytes
    assert "holding_reference" not in result


def test_v2_calendar_failure_does_not_suppress_valid_raw_price_reference(tmp_path):
    original=receipt().model_copy(update={"schema_version":"2","calendar_error_code":"CALENDAR_WATCHDOG_TIMEOUT"})
    _, result=persist_receipt(tmp_path,original)
    assert result["status"]=="OBSERVED_REFERENCE_ONLY"
    assert result["holding_reference"]=={"status":"BLOCKED","error_code":"CALENDAR_WATCHDOG_TIMEOUT"}
    assert load_receipt(tmp_path,A,B,END,now=NOW)["holding_reference"]==result["holding_reference"]


def test_calendar_outcome_schema_not_ambiguous(tmp_path):
    with pytest.raises(ValueError):
        persist_receipt(tmp_path,receipt().model_copy(update={"schema_version":"2"}))
    with pytest.raises(ValueError):
        persist_receipt(tmp_path,receipt().model_copy(update={"calendar_error_code":"MISSING"}))


def test_newer_complete_source_failure_withholds_old_pair(tmp_path):
    persist_receipt(tmp_path,receipt())
    failures=tuple(HistoricalCaptureFailure(provider=p,asset_type=a,error_code="WATCHDOG_TIMEOUT")
        for p,a in (("sina","STOCK"),("sina","ETF"),("baostock","STOCK")))
    failed=receipt().model_copy(update={"schema_version":"2","observed_at":NOW,
        "series":(),"failures":failures,"calendar_error_code":"CALENDAR_NOT_ATTEMPTED_MISSING_PAIR"})
    digest,result=persist_receipt(tmp_path,failed)
    assert result["status"]=="BLOCKED" and result["error_code"]=="MISSING_ASSET_HISTORY"
    loaded=load_receipt(tmp_path,A,B,END,now=NOW)
    assert loaded["normalized_observation_sha256"]==digest
    assert "reference" not in loaded


def combined_receipt():
    original = receipt()
    dates = tuple(r.day for r in scheduled_days(START, END) if r.is_trading_day)
    cal = CalendarObservation(first_requested=START, last_requested=END,
                              observed_at=NOW-timedelta(minutes=2), rows=scheduled_days(START, END))
    a = HistoricalCloseSeries(subject_id=A.symbol, currency="CNY", price_basis="RAW_CLOSE",
        source_label="baostock", closes=tuple(DailyClose(session=d, close=100. if i<10 else 32.)
                                               for i,d in enumerate(dates)))
    b = HistoricalCloseSeries(subject_id=B.symbol, currency="CNY", price_basis="RAW_CLOSE",
        source_label="sina", closes=tuple(DailyClose(session=d, close=100.) for d in dates))
    event = ShareCashDistribution(action_id="synthetic:1", subject_id=A.symbol,
        disclosed_date=dates[8], record_date=dates[9], ex_date=dates[10],
        post_units_numerator=3, pre_units_denominator=1, gross_cash_per_old_unit_cny="4",
        source_locator="https://example.invalid/disclosure", source_sha256="a"*64)
    return original.model_copy(update={"schema_version":"3", "calendar":cal, "series":(a,b),
        "share_cash_distributions":ShareCashDistributionInputs(events=(event,))})


def test_v3_combined_terms_are_persisted_rehashed_and_recomputed(tmp_path):
    r = combined_receipt()
    digest, computed = persist_receipt(tmp_path, r)
    assert computed["holding_reference"]["raw_full_window_pct"]["candidate"] == pytest.approx(-68)
    assert computed["holding_reference"]["share_cash_full_window_pct"]["candidate"] == pytest.approx(0)
    loaded = load_receipt(tmp_path, A, B, END, now=NOW)
    assert loaded["normalized_observation_sha256"] == digest and loaded["normalized_observation_rehashed"]
    assert loaded["holding_reference"] == computed["holding_reference"]
    assert not loaded["holding_reference"]["share_cash_original_bytes_verified"]
    assert not loaded["holding_reference"]["decision_authority"]


@pytest.mark.parametrize("updates", [{"schema_version":"1"}, {"schema_version":"2"},
                                    {"share_cash_distributions":None},
                                    {"share_cash_distributions":ShareCashDistributionInputs(events=())}])
def test_receipt_version_cannot_silently_discard_combined_terms(tmp_path, updates):
    with pytest.raises(ValueError):
        persist_receipt(tmp_path, combined_receipt().model_copy(update=updates))


def test_v2_canonical_encoding_is_unchanged(tmp_path):
    import hashlib
    import json

    original = receipt().model_copy(update={"schema_version":"2", "calendar_error_code":"MISSING"})
    payload = original.model_dump(mode="json")
    payload.pop("share_cash_distributions")
    old_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",",":"), allow_nan=False).encode()
    digest, _ = persist_receipt(tmp_path, original)
    assert digest == hashlib.sha256(old_bytes).hexdigest()
    assert (tmp_path/(digest+".json")).read_bytes() == old_bytes
