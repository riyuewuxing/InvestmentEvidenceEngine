from datetime import date

import pytest

from investment_evidence_engine.szse_pcf import parse_szse_pcf

XML = b"""<PCFFile xmlns="http://ts.szse.cn/Fund">
<SecurityID>159607</SecurityID><SecurityIDSource>102</SecurityIDSource>
<TradingDay>20260908</TradingDay><PreTradingDay>20260904</PreTradingDay>
<NAV>1.2345</NAV><NAVperCU>1234500.00</NAVperCU>
<CreationRedemptionUnit>1000000</CreationRedemptionUnit>
<Creation>N</Creation><Redemption>Y</Redemption><Publish>Y</Publish>
<CreationLimit>0</CreationLimit><RedemptionLimit>5000000</RedemptionLimit>
</PCFFile>"""


def parse(raw=XML):
    return parse_szse_pcf(raw, symbol="159607", session=date(2026, 9, 8))


def test_separate_directions_and_lagged_nav():
    result = parse()
    assert result["creation_allowed_reported"] is False
    assert result["redemption_allowed_reported"] is True
    assert result["nav_reference_day"] == "2026-09-04"
    assert result["caps_shares_raw"]["CreationLimit"] == 0
    assert result["caps_shares_raw"]["CreationLimitPerUser"] is None
    assert not result["actual_order_acceptance_verified"]
    assert not result["secondary_trading_status_inferred"]


@pytest.mark.parametrize(("old", "new"), [
    (b"159607", b"159696"), (b"102", b"101"),
    (b"20260908", b"20260907"), (b"20260904", b"20260908"),
    (b"<Creation>N", b"<Creation>UNKNOWN"),
    (b"<NAV>1.2345", b"<NAV>NaN"),
    (b"<CreationLimit>0", b"<CreationLimit>-1"),
    (b"<Creation>N</Creation>", b"<Creation>N</Creation><Creation>Y</Creation>"),
    (b"<Redemption>Y</Redemption>", b""),
    (b"http://ts.szse.cn/Fund", b"urn:other"),
])
def test_rejects_invalid_scope(old, new):
    with pytest.raises(ValueError):
        parse(XML.replace(old, new))


def test_forbids_dtd():
    with pytest.raises(ValueError):
        parse(b'<!DOCTYPE PCFFile [<!ENTITY x "1">]>' + XML)
