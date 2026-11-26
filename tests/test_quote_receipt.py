import base64
import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from investment_evidence_engine.historical_capture import PublicSecurity
from investment_evidence_engine.quote_receipt import (
    QuoteFailure,
    QuotePayload,
    QuoteReceipt,
    load_latest_quote,
    persist_quote_receipt,
    summarize_receipt,
)

NOW=datetime(2026,11,26,13,40,5,tzinfo=ZoneInfo("Asia/Shanghai"))
STOCK=PublicSecurity(symbol="600519",asset_type="STOCK")


def receipt():
    fields=["0"]*50
    for i,v in {2:STOCK.symbol,3:"100.02",9:"100.01",19:"100.02",30:"20261126134000"}.items():
        fields[i]=v
    raw=('v_'+STOCK.prefixed+'="'+"~".join(fields)+'";').encode()
    payload=QuotePayload(provider="tencent",observed_at=NOW,raw_base64=base64.b64encode(raw).decode(),
                         raw_sha256=hashlib.sha256(raw).hexdigest())
    return QuoteReceipt(subject=STOCK,captured_at=NOW,payloads=(payload,),
                        failures=(QuoteFailure(provider="sina",error_code="SYNTHETIC"),))


def test_bytes_reopened_and_staleness_recomputed(tmp_path):
    digest,_=persist_quote_receipt(tmp_path,receipt())
    fresh=load_latest_quote(tmp_path,STOCK,now=NOW)
    assert fresh["receipt_sha256"]==digest and fresh["receipt_rehashed"]
    assert fresh["observations"][0]["status"]=="OBSERVED_TOP_OF_BOOK_ONLY"
    stale=load_latest_quote(tmp_path,STOCK,now=NOW+timedelta(seconds=100))
    assert stale["status"]=="UNAVAILABLE"
    assert "bid_cny" not in stale["observations"][0]


def test_later_total_failure_does_not_return_older_quote(tmp_path):
    persist_quote_receipt(tmp_path,receipt())
    stamp=NOW+timedelta(seconds=1)
    failed=QuoteReceipt(subject=STOCK,captured_at=stamp,payloads=(),
        failures=tuple(QuoteFailure(provider=p,error_code="TIMEOUT") for p in ("tencent","sina")))
    digest,_=persist_quote_receipt(tmp_path,failed)
    result=load_latest_quote(tmp_path,STOCK,now=stamp)
    assert result["receipt_sha256"]==digest and result["status"]=="UNAVAILABLE"
    assert result["observations"]==[]


def test_tampering_and_missing_attempt_fail_closed(tmp_path):
    digest,_=persist_quote_receipt(tmp_path,receipt())
    path=tmp_path/(digest+".json")
    path.write_bytes(path.read_bytes()+b" ")
    with pytest.raises(ValueError,match="QUOTE_RECEIPT_HASH_MISMATCH"):
        load_latest_quote(tmp_path,STOCK,now=NOW)
    with pytest.raises(ValueError,match="QUOTE_ATTEMPT_COVERAGE_INVALID"):
        summarize_receipt(receipt().model_copy(update={"failures":()}),now=NOW)


def test_raw_body_hash_mismatch_not_accepted():
    original=receipt()
    broken=original.payloads[0].model_copy(update={"raw_sha256":"0"*64})
    with pytest.raises(ValueError,match="QUOTE_RAW_BYTES_HASH_MISMATCH"):
        summarize_receipt(original.model_copy(update={"payloads":(broken,)}),now=NOW)
