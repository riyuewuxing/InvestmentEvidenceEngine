import base64
import hashlib
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

import pytest

from investment_evidence_engine.historical_capture import PublicSecurity
from investment_evidence_engine.quote_receipt import (
    QuoteFailure,
    QuotePayload,
    QuoteReceipt,
    cost_walk_latest_quote,
    load_latest_quote,
    persist_quote_receipt,
    summarize_receipt,
    walk_latest_quote,
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


def test_depth_walk_requires_both_raw_sources(tmp_path):
    persist_quote_receipt(tmp_path,receipt())
    result=walk_latest_quote(tmp_path,STOCK,now=NOW,side="BUY",units=100)
    assert result["error_code"]=="DEPTH_REQUIRES_BOTH_SOURCES"
    assert "conditional_vwap_cny" not in result


def test_existing_empty_receipt_folder_is_unavailable(tmp_path):
    assert load_latest_quote(tmp_path,STOCK,now=NOW)["error_code"]=="NO_LOCAL_QUOTE_RECEIPT"
    assert walk_latest_quote(tmp_path,STOCK,now=NOW,side="BUY",units=100)["error_code"]=="NO_LOCAL_QUOTE_RECEIPT"


def matched_receipt():
    t=["0"]*50
    s=["0"]*33
    for i,v in {2:STOCK.symbol,3:"100.00",30:"20261126134000"}.items():
        t[i]=v
    for i,v in {3:"100.00",30:"2026-11-26",31:"13:40:00"}.items():
        s[i]=v
    for j in range(5):
        for k,price in enumerate((100-j*.01,100.01+j*.01)):
            ti=9+k*10+2*j
            si=10+k*10+2*j
            t[ti],t[ti+1]=f"{price:.2f}",str(j+1)
            s[si],s[si+1]=str((j+1)*100),f"{price:.2f}"
    raw=(('v_'+STOCK.prefixed+'="'+"~".join(t)+'";').encode(),
         ('var hq_str_'+STOCK.prefixed+'="'+",".join(s)+'";').encode())
    payloads=tuple(QuotePayload(provider=provider,observed_at=NOW,
        raw_base64=base64.b64encode(value).decode(),raw_sha256=hashlib.sha256(value).hexdigest())
        for provider,value in zip(("tencent","sina"),raw,strict=True))
    return QuoteReceipt(subject=STOCK,captured_at=NOW,payloads=payloads,failures=())


TERMS=dict(commission_rate=Decimal(".0003"),minimum_commission=Decimal("5"),
           transfer_rate=Decimal(".00001"),sell_stamp_rate=Decimal(".0005"))


def test_rehashed_static_depth_and_fee_do_not_double_count(tmp_path):
    digest,_=persist_quote_receipt(tmp_path,matched_receipt())
    buy=cost_walk_latest_quote(tmp_path,STOCK,now=NOW,side="BUY",units=200,**TERMS)
    assert buy["status"]=="CONDITIONAL_STATIC_BOOK_AND_FEE_ONLY"
    assert buy["receipt_sha256"]==digest and buy["receipt_rehashed"]
    assert buy["conditional_notional_decimal_cny"]=="20003.00"
    assert buy["commission_cny"]=="6.00" and buy["transfer_fee_cny"]=="0.20"
    assert buy["stamp_tax_cny"]=="0.00"
    assert buy["conditional_cash_required_or_received_cny"]=="20009.20"
    sell=cost_walk_latest_quote(tmp_path,STOCK,now=NOW,side="SELL",units=200,**TERMS)
    assert Decimal(sell["conditional_notional_decimal_cny"])==Decimal("19999")
    assert sell["stamp_tax_cny"]=="10.00"
    assert sell["conditional_cash_required_or_received_cny"]=="19982.80"
    assert not buy["actual_broker_fee_verified"] and not buy["actual_fill_verified"]
    assert not sell["sellable_inventory_verified"] and not sell["decision_authority"]


def test_unavailable_depth_withholds_fees_and_notional(tmp_path):
    persist_quote_receipt(tmp_path,matched_receipt())
    for now,units in ((NOW+timedelta(seconds=100),100),(NOW,1600)):
        result=cost_walk_latest_quote(tmp_path,STOCK,now=now,side="BUY",units=units,**TERMS)
        assert result["status"]!="CONDITIONAL_STATIC_BOOK_AND_FEE_ONLY"
        assert "total_explicit_fee_cny" not in result and "conditional_cash_required_or_received_cny" not in result
    with pytest.raises(ValueError,match="WHOLE_100_UNITS"):
        cost_walk_latest_quote(tmp_path,STOCK,now=NOW,side="BUY",units=101,**TERMS)


def test_cost_walk_is_independent_of_caller_decimal_precision(tmp_path):
    persist_quote_receipt(tmp_path,matched_receipt())
    with localcontext() as ctx:
        ctx.prec=3
        result=cost_walk_latest_quote(tmp_path,STOCK,now=NOW,side="BUY",units=200,**TERMS)
    assert result["conditional_cash_required_or_received_cny"]=="20009.20"
    assert result["total_explicit_fee_cny"]=="6.20"
