from datetime import date

import pytest

from investment_evidence_engine.cash_fees import CashFeeScenario, CommissionScenario, fee_scenario
from investment_evidence_engine.historical_capture import PublicSecurity


def inputs(kind="STOCK",notional=10000.,orders=1,commission=True):
    return CashFeeScenario(subject=PublicSecurity(symbol="600519" if kind=="STOCK" else "510050",asset_type=kind),
        kind="DOMESTIC_A_STOCK" if kind=="STOCK" else "DOMESTIC_EQUITY_ETF_SECONDARY",
        reference_session=date(2026,11,25),entry_notional_cny=notional,exit_notional_cny=notional,
        entry_orders=orders,exit_orders=orders,commission=CommissionScenario(inclusive_rate_bps=3.,
            minimum_per_order_cny=5.,note="synthetic assumed terms") if commission else None)


def test_stock_does_not_double_count_embedded_regulatory_charge():
    result=fee_scenario(inputs())
    assert result["buy"]["embedded_regulatory_fee_reference_cny"]==0.54
    assert result["buy"]["transfer_fee_reference_cny"]==0.1
    assert result["buy"]["stamp_tax_reference_cny"]==0.
    assert result["sell"]["stamp_tax_reference_cny"]==5.
    assert result["round_trip_explicit_fee_cny"]==15.2
    assert result["round_trip_explicit_fee_bps_of_entry"]==pytest.approx(15.2)
    assert not result["actual_broker_fee_verified"] and not result["decision_authority"]


def test_equity_etf_no_stock_transfer_or_stamp():
    result=fee_scenario(inputs("ETF"))
    assert result["buy"]["embedded_regulatory_fee_reference_cny"]==0.4
    assert result["sell"]["separate_public_fee_reference_cny"]==0.
    assert result["round_trip_explicit_fee_cny"]==10.


def test_minimum_applied_per_order():
    result=fee_scenario(inputs(notional=10000.,orders=4))
    assert result["buy"]["inclusive_commission_scenario_cny"]==20.
    assert result["round_trip_explicit_fee_cny"]==45.24


def test_unknown_broker_cost_not_zero_or_guessed():
    result=fee_scenario(inputs(commission=False))
    assert result["round_trip_explicit_fee_cny"] is None
    assert result["sell"]["stamp_tax_reference_cny"]==5.


@pytest.mark.parametrize("changes",[
    {"reference_session":date(2025,12,31)},{"reference_session":date(2027,1,1)},
    {"entry_notional_cny":float("inf")},{"entry_orders":0},{"kind":"DOMESTIC_EQUITY_ETF_SECONDARY"},
    {"commission":CommissionScenario(inclusive_rate_bps=.1,minimum_per_order_cny=5.,note="synthetic")},
])
def test_invalid_scope_revalidated(changes):
    with pytest.raises(ValueError):
        fee_scenario(inputs().model_copy(update=changes))


def test_fee_only_return_is_not_total_or_expected_return():
    base=inputs().model_copy(update={"exit_notional_cny":10100.})
    result=fee_scenario(base)
    assert result["gross_price_change_pct"]==1.
    assert result["conditional_fee_only_net_return_pct"]==pytest.approx((10100-10.15)/(10000+5.10)*100-100)
    assert not result["total_holding_cost_estimated"]
    assert fee_scenario(inputs(commission=False))["conditional_fee_only_net_return_pct"] is None


def test_subcent_or_holiday_invalid():
    for changes in ({"entry_notional_cny":100.001},{"entry_notional_cny":.01,"entry_orders":2},
                    {"reference_session":date(2026,10,1)}):
        with pytest.raises(ValueError):
            fee_scenario(inputs().model_copy(update=changes))


def test_ordinary_standard_minimum_fee_scope():
    with pytest.raises(ValueError):
        CommissionScenario(inclusive_rate_bps=3.,minimum_per_order_cny=0.,note="unverified special term")
