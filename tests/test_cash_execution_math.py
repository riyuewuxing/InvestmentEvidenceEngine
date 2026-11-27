from datetime import date
from decimal import Decimal, localcontext

import pytest

from investment_evidence_engine.cash_execution_math import affordable_units, order_fees, price_band
from investment_evidence_engine.cash_fees import CashFeeScenario, CommissionScenario, fee_scenario
from investment_evidence_engine.historical_capture import PublicSecurity

D = Decimal
TERMS = dict(commission_rate=D(".0003"), minimum_commission=D("5"),
             transfer_rate=D(".00001"), sell_stamp_rate=D(".0005"))


@pytest.mark.parametrize("reference,rate,expected", [
    ("4.35", ".10", ("3.92", "4.79")),
    (".04", ".10", (".03", ".05")),
    (".01", ".10", (".01", ".02")),
    ("1.42", ".05", ("1.35", "1.49")),
    ("1.49", ".10", ("1.34", "1.64")),
    ("111.01", ".10", ("99.91", "122.11")),
    ("10.00", ".20", ("8.00", "12.00")),
])
def test_price_band(reference, rate, expected):
    with localcontext() as ctx:
        ctx.prec = 3
        assert price_band(D(reference), D(rate)) == tuple(map(D, expected))


@pytest.mark.parametrize("reference,rate", [
    ("0", ".1"), ("0.009", ".1"), ("10.001", ".1"), ("NaN", ".1"),
    ("10", "0"), ("10", "1"), ("10", "Infinity"),
])
def test_invalid_band(reference, rate):
    with pytest.raises(ValueError):
        price_band(D(reference), D(rate))


@pytest.mark.parametrize("notional", ["10000", "2500", "100.01", "1000000"])
def test_order_cost_matches_existing_reviewed_fee_control(notional):
    amount = D(notional)
    scenario = fee_scenario(CashFeeScenario(subject=PublicSecurity(symbol="600519", asset_type="STOCK"),
        kind="DOMESTIC_A_STOCK", reference_session=date(2026, 11, 25),
        entry_notional_cny=float(amount), exit_notional_cny=float(amount), entry_orders=1, exit_orders=1,
        commission=CommissionScenario(inclusive_rate_bps=3., minimum_per_order_cny=5., note="synthetic")))
    for side, key in (("BUY", "buy"), ("SELL", "sell")):
        fee = order_fees(amount, side=side, **TERMS)
        assert fee.total == D(str(scenario[key]["explicit_fee_scenario_cny"]))
        assert fee.transfer == D(str(scenario[key]["transfer_fee_reference_cny"]))
        assert fee.stamp == D(str(scenario[key]["stamp_tax_reference_cny"]))


def test_no_double_count_and_half_up():
    assert order_fees(D("10000"), side="BUY", **TERMS).total == D("5.10")
    assert order_fees(D("10000"), side="SELL", **TERMS).total == D("10.10")
    assert order_fees(D("2500"), side="BUY", **TERMS).transfer == D(".03")


@pytest.mark.parametrize("cash,price,min_units,increment", [
    ("10005", "100", 100, 100), ("10005.10", "100", 100, 100),
    ("2005.02", "10", 200, 1), ("1234567.89", "12.34", 100, 100),
    ("0", "1", 100, 100), ("100", "1", 200, 1),
])
def test_affordable_units_is_maximal_and_never_negative_cash(cash, price, min_units, increment):
    cash, price = D(cash), D(price)
    args = {key: value for key, value in TERMS.items() if key != "sell_stamp_rate"}
    qty = affordable_units(cash, price, minimum_units=min_units, increment=increment, **args)
    if qty:
        assert qty >= min_units and (qty - min_units) % increment == 0
        assert qty * price + order_fees(qty * price, side="BUY", **TERMS).total <= cash
    next_qty = qty + increment if qty else min_units
    assert next_qty * price + order_fees(next_qty * price, side="BUY", **TERMS).total > cash


def test_invalid_amounts_and_rates_rejected():
    for amount in (D("0"), D("100.001"), D("NaN")):
        with pytest.raises(ValueError):
            order_fees(amount, side="BUY", **TERMS)
    with pytest.raises(ValueError):
        order_fees(D("100"), side="BUY", **(TERMS | {"transfer_rate": D("-0.01")}))
    with pytest.raises(ValueError):
        order_fees(D("100"), side="UNKNOWN", **TERMS)
