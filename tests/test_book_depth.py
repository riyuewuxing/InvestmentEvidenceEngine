from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from investment_evidence_engine.book_depth import compare_displayed_depth, depth_walk_scenario
from investment_evidence_engine.historical_capture import PublicSecurity

NOW=datetime(2026,11,26,13,40,5,tzinfo=ZoneInfo("Asia/Shanghai"))
SUB=PublicSecurity(symbol="600519",asset_type="STOCK")


def raws(*,sina_multiplier=100,sina_time="13:40:00"):
    t=["0"]*50
    s=["0"]*33
    for i,v in {2:SUB.symbol,3:"100.00",30:"20261126134000"}.items():
        t[i]=v
    for i,v in {3:"100.00",30:"2026-11-26",31:sina_time}.items():
        s[i]=v
    for j in range(5):
        for k,price in enumerate((100-j*.01,100.01+j*.01)):
            p=f"{price:.2f}"
            ti=9+k*10+2*j
            si=10+k*10+2*j
            t[ti],t[ti+1]=p,str(j+1)
            s[si],s[si+1]=str((j+1)*sina_multiplier),p
    return ('v_'+SUB.prefixed+'="'+"~".join(t)+'";').encode(),('var hq_str_'+SUB.prefixed+'="'+",".join(s)+'";').encode()


def depth(**kw):
    a,b=raws(**kw)
    return compare_displayed_depth(SUB,a,NOW,b,NOW,now=NOW)


def test_exact_same_timestamp_five_levels_and_units():
    result=depth()
    assert result["status"]=="MATCHED_DISPLAYED_DEPTH_ONLY"
    assert result["ask_displayed_units"]==1500
    assert result["bids"][0]=={"price_cny":100.,"displayed_units":100}
    assert not result["actual_fill_verified"]


def test_unit_or_timestamp_conflict_withholds_book():
    for kw in ({"sina_multiplier":1},{"sina_time":"13:40:01"}):
        result=depth(**kw)
        assert result["status"]=="UNAVAILABLE" and "bids" not in result


def test_static_walk_never_claims_execution_or_extrapolates():
    a,b=raws()
    result=depth_walk_scenario(SUB,a,NOW,b,NOW,now=NOW,side="BUY",units=200)
    assert result["conditional_vwap_cny"]==pytest.approx(100.015)
    assert result["adverse_bps_from_best_quote"]==pytest.approx(.005/100.01*10000)
    assert not result["actual_fill_verified"] and not result["impact_cost_estimated"]
    missing=depth_walk_scenario(SUB,a,NOW,b,NOW,now=NOW,side="SELL",units=1600)
    assert missing["status"]=="INSUFFICIENT_DISPLAYED_DEPTH"
    assert "conditional_vwap_cny" not in missing and missing["uncovered_units"]==100
    stale=compare_displayed_depth(SUB,a,NOW,b,NOW,now=NOW+timedelta(seconds=100))
    assert stale["status"]=="UNAVAILABLE"
