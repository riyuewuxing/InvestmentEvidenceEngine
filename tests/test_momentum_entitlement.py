from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from investment_evidence_engine.cash_entitlement import CashEntitlementTerms
from investment_evidence_engine.historical_capture import PublicSecurity
from investment_evidence_engine.holding_risk import CashDistribution, CashDistributionInputs
from investment_evidence_engine.market_calendar import scheduled_days
from investment_evidence_engine.momentum_entitlement import (
    momentum_entitlement_profile,
    segregated_entitlement_metrics,
)


def test_ex_open_buy_excluded_ex_open_sell_included():
    events = {0: Decimal("1"), 1: Decimal("1"), 2: Decimal("1")}
    result = segregated_entitlement_metrics([10., 10., 10.], [0, 1], 0, events)
    assert [x["held_at_previous_record_close"] for x in result["events"]] == [False, False, True]
    assert result["gross_entitlement_increment_pp"] == pytest.approx(10)
    sold = segregated_entitlement_metrics([10., 9., 9.], [1, 0], 0, {1: Decimal("1")})
    assert sold["price_only"]["net_price_change_pct"] == pytest.approx(-10)
    assert sold["price_plus_nominal_gross_entitlement_change_pct"] == pytest.approx(0)
    assert sold["events"][0]["held_at_previous_record_close"]


def test_terminal_entitlement_not_reinvested_or_charged_sale_fee():
    result = segregated_entitlement_metrics([10., 10.], [1], 100, {1: Decimal("1")})
    assert result["gross_entitlement_increment_pp"] == pytest.approx(9.9)
    assert result["price_only"]["net_price_change_pct"] == pytest.approx(-1.99)
    assert result["price_plus_nominal_gross_entitlement_change_pct"] == pytest.approx(7.91)
    assert not result["actual_payment_verified"]
    later = segregated_entitlement_metrics([10., 10., 10., 10.], [1, 0, 1], 0,
                                          {1: Decimal("1"), 3: Decimal("1")})
    assert later["gross_entitlement_increment_pp"] == pytest.approx(20)


@pytest.mark.parametrize("fault", [{True: Decimal("1")}, {2: Decimal("1")},
                                 {1: Decimal("NaN")}, {1: .1}, {1: Decimal("-1")}])
def test_invalid_entitlement_events(fault):
    with pytest.raises(ValueError):
        segregated_entitlement_metrics([10., 10.], [1], 0, fault)


def fixture():
    dates = tuple(r.day for r in scheduled_days(date(2025, 1, 2), date(2026, 11, 25)) if r.is_trading_day)
    symbol = PublicSecurity(symbol="000035", asset_type="STOCK")
    terms = CashEntitlementTerms(symbol=symbol.symbol, disclosed_date=date(2025, 7, 30),
        record_date=date(2025, 8, 5), ex_date=date(2025, 8, 6),
        source_locator="https://example.invalid/cash.pdf", total_shares=2500783182, excluded_shares=112750413,
        gross_per_share=Decimal("0.0352"), declared_total_cash=Decimal("84058753.47"),
        declared_reference_deduction=Decimal("0.0336129"))
    event = CashDistribution(subject_id=symbol.symbol, disclosed_date=terms.disclosed_date,
        ex_date=terms.ex_date, gross_cash_per_unit_cny=float(terms.gross_per_share), source_locator=terms.source_locator)
    return dates, [10.+i/100 for i in range(len(dates))], symbol, terms, CashDistributionInputs(events=(event,))


def test_profile_preserves_existing_price_baseline_and_uses_gross_not_reference():
    days, values, subject, terms, events = fixture()
    report = momentum_entitlement_profile(days, values, values, subject=subject, events=events,
                                          reference_terms=(terms,))
    train = report["segments"][0]["stress"][0]["constant_invested"]
    assert train["events"][0]["gross_cash_per_share_cny"] == "0.0352"
    assert train["events"][0]["record_date"] == "2025-08-05"
    assert train["price_only"] == report["price_only_baseline"]["segments"][0]["stress"][0]["constant_invested"]
    assert not report["total_return_certified"] and not report["pit_safe"]
    assert report["segments"][2]["stress"][0]["constant_invested"]["gross_entitlement_increment_pp"] == 0


@pytest.mark.parametrize("fault", ["missing", "record", "duplicate", "gap"])
def test_profile_requires_event_identity_and_complete_calendar(fault):
    days, values, subject, terms, events = fixture()
    supplied = (terms,)
    if fault == "missing":
        supplied = ()
    elif fault == "record":
        supplied = (replace(terms, record_date=date(2025, 8, 4)),)
    elif fault == "duplicate":
        supplied = (terms, terms)
    else:
        days = days[:50]+days[51:]
        values = values[:50]+values[51:]
    with pytest.raises(ValueError):
        momentum_entitlement_profile(days, values, values, subject=subject, events=events,
                                     reference_terms=supplied)
