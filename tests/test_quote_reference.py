from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from investment_evidence_engine.historical_capture import PublicSecurity
from investment_evidence_engine.quote_reference import (
    crosscheck_quotes,
    parse_quote,
    quote_reference,
)

SH=ZoneInfo("Asia/Shanghai")
NOW=datetime(2026,11,26,13,40,5,tzinfo=SH)
STOCK=PublicSecurity(symbol="600519",asset_type="STOCK")
ETF=PublicSecurity(symbol="510050",asset_type="ETF")


def tencent(subject=STOCK,stamp="20261126134000",bid="100.01",ask="100.02",last="100.02"):
    fields=["0"]*50
    for i,v in {2:subject.symbol,3:last,9:bid,19:ask,30:stamp}.items():
        fields[i]=v
    return ('v_'+subject.prefixed+'="'+"~".join(fields)+'";').encode()


def sina(subject=STOCK,bid="100.01",ask="100.02"):
    fields=["0"]*33
    for i,v in {3:"100.02",11:bid,21:ask,30:"2026-11-26",31:"13:40:00"}.items():
        fields[i]=v
    return ('var hq_str_'+subject.prefixed+'="'+",".join(fields)+'";').encode()


def test_two_source_top_of_book_and_spread_math():
    a=parse_quote(tencent(),STOCK,"tencent",NOW)
    b=parse_quote(sina(),STOCK,"sina",NOW)
    result=quote_reference(a,now=NOW)
    assert result["status"]=="OBSERVED_TOP_OF_BOOK_ONLY"
    assert result["full_quoted_spread_bps_of_mid"]==pytest.approx(.01/100.015*10000)
    assert result["instantaneous_hypothetical_roundtrip_loss_bps_of_ask"]==pytest.approx(.01/100.02*10000)
    assert crosscheck_quotes(a,b,now=NOW)["status"]=="DISPLAYED_BID_ASK_MATCH"
    assert not result["actual_fill_verified"] and not result["decision_authority"]


@pytest.mark.parametrize("raw",[
    tencent(ETF),tencent(bid="0"),tencent(bid="100.03"),tencent(bid="100.001"),
    tencent(stamp="20261126134006"),b"v_sh600519=\"bad\";",tencent()+tencent(),
])
def test_invalid_identity_timestamp_price_or_extra_wire(raw):
    with pytest.raises(ValueError):
        parse_quote(raw,STOCK,"tencent",NOW)


def test_stale_and_lunch_quotes_withhold_numbers():
    a=parse_quote(tencent(),STOCK,"tencent",NOW)
    stale=quote_reference(a,now=NOW+timedelta(seconds=100))
    assert stale["error_code"]=="QUOTE_STALE" and "bid_cny" not in stale
    lunch=datetime(2026,11,26,12,0,5,tzinfo=SH)
    q=parse_quote(tencent(stamp="20261126120000"),STOCK,"tencent",lunch)
    assert quote_reference(q,now=lunch)["error_code"]=="OUTSIDE_CONTINUOUS_AUCTION"


def test_etf_tick_and_different_displayed_prices():
    a=parse_quote(tencent(ETF,bid="2.501",ask="2.502",last="2.502"),ETF,"tencent",NOW)
    assert quote_reference(a,now=NOW)["status"]=="OBSERVED_TOP_OF_BOOK_ONLY"
    a=parse_quote(tencent(),STOCK,"tencent",NOW)
    b=parse_quote(sina(ask="100.03"),STOCK,"sina",NOW)
    assert crosscheck_quotes(a,b,now=NOW)["status"]=="DIFFERENT_DISPLAYED_PRICES"


def test_constructed_crossed_quote_revalidated():
    a=parse_quote(tencent(),STOCK,"tencent",NOW)
    with pytest.raises(ValueError):
        quote_reference(a.model_copy(update={"bid":100.03}),now=NOW)
