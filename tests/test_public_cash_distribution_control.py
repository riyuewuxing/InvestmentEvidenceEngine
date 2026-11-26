from datetime import date
from decimal import Decimal

import pytest

from investment_evidence_engine.historical_reference import DailyClose, HistoricalCloseSeries
from investment_evidence_engine.market_calendar import scheduled_days
from investment_evidence_engine.public_cash_distribution_control import (
    FIRST,
    LAST,
    cash_sensitivity,
    checked_fields,
)

STOCK = ("证券代码：000035 中国天楹股份有限公司 2025年年度权益分派实施公告 TY2026-37 "
         "股权登记日：2026年8月19日；除权除息日：2026年8月20日 "
         "每10股派息（含税）：0.36元 除权前总股本：2,388,032,769股 "
         "除权后总股本：2,388,032,769股")
ETF_FIRST = "华泰柏瑞沪深300交易型开放式指数证券投资基金分红公告 2026年1月12日"
ETF_PAGE = ("基金主代码 510300 权益登记日 2026年1月16日 除息日 2026年1月19日 "
            "现金红利发放日 2026年1月27日 本次分红方案（单位：元/10份基金份额） 1.2300 "
            "2026年第一次分红")


def test_reviewed_fields():
    assert checked_fields("stock", STOCK, STOCK)["gross_cash_per_unit_cny"] == "0.036"
    assert Decimal(checked_fields("etf", ETF_FIRST, ETF_PAGE)["gross_cash_per_unit_cny"]) == Decimal("0.123")


@pytest.mark.parametrize("wrong", [STOCK.replace("0.36元", "0.63元"),
                                   STOCK.replace("8月20日", "8月21日"),
                                   STOCK.replace("000035", "000036"),
                                   STOCK.replace("2,388,032,769股", "2,000,000,000股")])
def test_stock_rejects_mismatched_reviewed_fields(wrong):
    with pytest.raises(ValueError, match="DISTRIBUTION_"):
        checked_fields("stock", wrong, wrong)


@pytest.mark.parametrize("wrong", [ETF_PAGE.replace("510300", "510050"),
                                   ETF_PAGE.replace("1.2300", "1.3200"),
                                   ETF_PAGE.replace("1月19日", "1月20日"),
                                   ETF_PAGE.replace("1月27日", "1月19日")])
def test_etf_rejects_mismatched_reviewed_fields(wrong):
    with pytest.raises(ValueError, match="DISTRIBUTION_"):
        checked_fields("etf", ETF_FIRST, wrong)


def test_single_event_cash_sensitivity_and_scope():
    sessions = tuple(x.day for x in scheduled_days(FIRST, LAST) if x.is_trading_day)
    event = date(2026, 8, 20)
    series = HistoricalCloseSeries(subject_id="000035", currency="CNY", price_basis="RAW_CLOSE",
        source_label="sina", closes=tuple(DailyClose(session=d, close=9.0 if d >= event else 10.0)
                                          for d in sessions))
    r = cash_sensitivity(series, ex_date=event, cash=Decimal("1"), sessions=sessions)
    assert r["event_price_return_pct"] == pytest.approx(-10)
    assert r["event_gross_entitlement_return_pct"] == pytest.approx(0)
    assert r["full_one_event_reinvested_return_pct"] == pytest.approx(0)
    with pytest.raises(ValueError, match="EVENT_SCOPE"):
        cash_sensitivity(series, ex_date=sessions[0], cash=Decimal("1"), sessions=sessions)
    with pytest.raises(ValueError, match="SESSION_SCOPE"):
        cash_sensitivity(series, ex_date=event, cash=Decimal("1"), sessions=sessions[1:])
    with pytest.raises(ValueError, match="EVENT_SCOPE"):
        cash_sensitivity(series, ex_date=event, cash=Decimal("NaN"), sessions=sessions)


def test_payment_field_provenance_is_not_overstated():
    stock = checked_fields("stock", STOCK, STOCK)
    etf = checked_fields("etf", ETF_FIRST, ETF_PAGE)
    assert stock["payment_day_parsed_from_selected_pages"] is False
    assert stock["declared_day_parsed_from_selected_pages"] is False
    assert stock["payment_day_scope"] == "DELEGATED_A_SHARE_PAYMENTS_ONLY"
    assert etf["payment_day_parsed_from_selected_pages"] is True
    assert etf["declared_day_parsed_from_selected_pages"] is True
    assert stock["declared_day_not_verified_publication_clock"] is True
    assert etf["declared_day_not_verified_publication_clock"] is True
