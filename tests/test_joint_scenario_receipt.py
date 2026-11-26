from datetime import date, timedelta

import pytest

from investment_evidence_engine.historical_receipt import HistoricalReceipt, persist_receipt
from investment_evidence_engine.historical_reference import DailyClose, HistoricalCloseSeries
from investment_evidence_engine.joint_scenario_receipt import (
    JointScenarioReceipt,
    load_joint_receipt,
    load_pair_anchor,
    persist_joint_receipt,
)
from investment_evidence_engine.market_calendar import CalendarObservation, scheduled_days

from test_joint_scenarios import ANCHOR, DAY, ETF, NOW, STOCK, inputs


def pair(*,price_conflict=False):
    first=date(2026,8,24)
    cal=CalendarObservation(first_requested=first,last_requested=DAY,observed_at=NOW-timedelta(minutes=1),
                            rows=scheduled_days(first,DAY))
    days=tuple(x.day for x in cal.rows if x.is_trading_day)
    def series(subject,provider,price):
        return HistoricalCloseSeries(subject_id=subject.symbol,currency="CNY",price_basis="RAW_CLOSE",
            source_label=provider,closes=tuple(DailyClose(session=d,close=price) for d in days))
    return HistoricalReceipt(schema_version="2",candidate=STOCK,alternative=ETF,first_requested=first,last_completed=DAY,
        observed_at=NOW,akshare_version="synthetic",attempted_providers=("baostock","tencent","sina"),
        series=(series(STOCK,"baostock",10.),series(STOCK,"tencent",10.01 if price_conflict else 10.),
                series(STOCK,"sina",10.),series(ETF,"sina",2.),series(ETF,"tencent",2.)),
        calendar=cal)


def test_exact_historical_pair_and_frozen_scenario_rederived(tmp_path):
    data=tmp_path/"pair"
    digest,_=persist_receipt(data,pair())
    anchor=load_pair_anchor(data,STOCK,ETF,DAY,now=NOW)
    assert anchor.normalized_pair_sha256==digest and anchor.stock_raw_close_cny==10.
    receipt=JointScenarioReceipt(anchor=anchor,assumptions=inputs(),recorded_at=NOW,expires_at=NOW+timedelta(hours=1))
    folder=tmp_path/"scenarios"
    sha,result=persist_joint_receipt(folder,receipt)
    loaded=load_joint_receipt(folder,anchor,now=NOW+timedelta(minutes=1))
    assert loaded["scenario_receipt_sha256"]==sha and loaded["scenario_receipt_rehashed"]
    assert loaded["states"]==result["states"]
    assert not loaded["formal_comparison_eligible"]
    stale=load_joint_receipt(folder,anchor,now=NOW+timedelta(hours=1))
    assert stale["error_code"]=="JOINT_SCENARIO_EXPIRED" and "states" not in stale


def test_anchor_change_and_tampering_fail_closed(tmp_path):
    receipt=JointScenarioReceipt(anchor=ANCHOR,assumptions=inputs(),recorded_at=NOW,expires_at=NOW+timedelta(hours=1))
    sha,_=persist_joint_receipt(tmp_path,receipt)
    other=ANCHOR.model_copy(update={"normalized_pair_sha256":"b"*64})
    with pytest.raises(ValueError,match="SCOPE"):
        load_joint_receipt(tmp_path,other,now=NOW)
    path=tmp_path/(sha+".json")
    path.write_bytes(path.read_bytes()+b" ")
    with pytest.raises(ValueError,match="HASH"):
        load_joint_receipt(tmp_path,ANCHOR,now=NOW)


def test_missing_or_nonexact_pair_does_not_create_anchor(tmp_path):
    with pytest.raises(ValueError,match="PAIR_REQUIRED"):
        load_pair_anchor(tmp_path,STOCK,ETF,DAY,now=NOW)
    persist_receipt(tmp_path,pair(price_conflict=True))
    with pytest.raises(ValueError,match="JOINT_"):
        load_pair_anchor(tmp_path,STOCK,ETF,DAY,now=NOW)


def test_expiry_and_latest_no_fallback(tmp_path):
    old=JointScenarioReceipt(anchor=ANCHOR,assumptions=inputs(),recorded_at=NOW,
        expires_at=NOW+timedelta(hours=2))
    persist_joint_receipt(tmp_path,old)
    later=old.model_copy(update={"recorded_at":NOW+timedelta(minutes=1),
                                 "expires_at":NOW+timedelta(minutes=2)})
    sha,_=persist_joint_receipt(tmp_path,later)
    result=load_joint_receipt(tmp_path,ANCHOR,now=NOW+timedelta(minutes=3))
    assert result["scenario_receipt_sha256"]==sha and result["error_code"]=="JOINT_SCENARIO_EXPIRED"
    with pytest.raises(ValueError,match="EXPIRY"):
        persist_joint_receipt(tmp_path,old.model_copy(update={"expires_at":NOW+timedelta(days=2)}))
