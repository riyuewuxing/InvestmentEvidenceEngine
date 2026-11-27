from datetime import datetime

import pytest

from investment_evidence_engine.intraday_t_scenarios import (
    FeeAssumptions,
    TAccountReference,
    TLeg,
    TScenario,
    compare_intraday_t,
)

FEE = FeeAssumptions(commission_rate="0.0003", minimum_commission_cny="5",
                     transfer_rate="0.00001", sell_stamp_rate="0.0005")


def make(**kwargs):
    inputs = dict(session_date="2026-11-27", calendar_state="ASSUMED_TRADING_DAY",
                  reference_close_cny="10.00", limit_rate="0.1",
                  minimum_buy_units=100, buy_increment=100, quantity=100,
                  first=TLeg(at="2026-11-27T10:00:00+08:00", buy_price_cny="9.80",
                             sell_price_cny="9.79", buy_fill="ASSUME_FILLED",
                             sell_fill="ASSUME_FILLED", market_state="ASSUMED_OPEN"),
                  second=TLeg(at="2026-11-27T14:30:00+08:00", buy_price_cny="10.20",
                              sell_price_cny="10.19", buy_fill="ASSUME_FILLED",
                              sell_fill="ASSUME_FILLED", market_state="ASSUMED_OPEN"),
                  terminal_mark_cny="10.30", terminal_mark_at="2026-11-27T15:00:00+08:00",
                  fees=FEE)
    return TScenario(**(inputs | kwargs))


def account(cash="2000", old=100):
    return TAccountReference(cash_cny=cash, held_units=100, sellable_old_units=old)


def test_same_inventory_and_common_mark_after_completed_two_legs():
    result = compare_intraday_t(account(), make())
    assert result["no_action"]["terminal_equity_cny"] == "3030.00"
    a, b = result["positive_t"], result["reverse_t"]
    assert a["status"] == b["status"] == "PAIRED_CONDITIONAL"
    assert a["matched_net_cash_delta_cny"] == "28.47"
    assert b["matched_net_cash_delta_cny"] == "-51.51"
    assert a["terminal_held_units"] == b["terminal_held_units"] == 100
    assert a["terminal_sellable_old_units"] == b["terminal_sellable_old_units"] == 0
    assert a["terminal_new_locked_units"] == b["terminal_new_locked_units"] == 100
    assert a["terminal_equity_cny"] == "3058.47"
    assert b["terminal_equity_cny"] == "2978.49"
    assert not result["actual_fills_verified"] and not result["decision_authority"]


def test_sell_first_funds_repurchase_but_does_not_assume_buy_first_cash():
    result = compare_intraday_t(account(cash="100"), make())
    assert result["positive_t"]["reason"] == "INSUFFICIENT_CASH_INCLUDING_FEES"
    assert result["positive_t"]["terminal_held_units"] == 100
    assert result["reverse_t"]["status"] == "PAIRED_CONDITIONAL"


def test_old_inventory_lock_and_unknown_never_count_new_purchase_as_sellable():
    for old, expected in [(0, "BLOCKED_BEFORE_FIRST"), (None, "UNKNOWN_BEFORE_FIRST")]:
        result = compare_intraday_t(account(old=old), make())
        assert result["positive_t"]["status"] == result["reverse_t"]["status"] == expected


def test_unpaired_buy_and_sell_are_marked_against_no_action():
    scenario = make()
    second = scenario.second.model_copy(update={"buy_fill": "ASSUME_NOT_FILLED", "sell_fill": "ASSUME_NOT_FILLED"})
    result = compare_intraday_t(account(), make(second=second))
    a, b = result["positive_t"], result["reverse_t"]
    assert a["status"] == b["status"] == "UNPAIRED_CONDITIONAL"
    assert a["position_delta_units"] == 100 and b["position_delta_units"] == -100
    assert a["delta_vs_no_action_cny"] == "44.99"
    assert b["delta_vs_no_action_cny"] == "-56.50"
    assert a["matched_net_cash_delta_cny"] is None


def test_unknown_second_never_imputes_terminal_wealth():
    scenario = make()
    result = compare_intraday_t(account(), make(second=scenario.second.model_copy(update={"sell_fill": "UNKNOWN"})))
    a = result["positive_t"]
    assert a["status"] == "UNKNOWN_SECOND_LEG"
    assert a["terminal_cash_cny"] is None and a["delta_vs_no_action_cny"] is None
    assert a["conditional_state_after_first"]["held_units"] == 200
    assert a["conditional_state_after_first"]["sellable_old_units"] == 100


def test_reverse_repurchase_can_fail_after_valid_sale():
    result = compare_intraday_t(account(cash="0"), make())
    b = result["reverse_t"]
    assert b["status"] == "UNPAIRED_CONDITIONAL"
    assert b["reason"] == "INSUFFICIENT_CASH_INCLUDING_FEES"
    assert b["terminal_held_units"] == 0


def test_fee_and_calendar_unknown_are_not_zero_fee_scenarios():
    for scenario in (make(fees=None), make(calendar_state="UNKNOWN"),
                     make(reference_close_cny=None, limit_rate=None)):
        result = compare_intraday_t(account(), scenario)
        assert result["positive_t"]["status"] == result["reverse_t"]["status"] == "UNKNOWN_BEFORE_FIRST"


def test_adverse_limit_queue_is_unknown_even_with_assume_fill():
    first = make().first.model_copy(update={"buy_price_cny": "11.00"})
    result = compare_intraday_t(account(), make(first=first))
    assert result["positive_t"]["reason"] == "ADVERSE_LIMIT_QUEUE_UNVERIFIED"
    assert result["positive_t"]["terminal_held_units"] is None


def test_same_timestamp_or_auction_or_cross_session_rejected():
    for at in ("2026-11-27T10:00:00+08:00", "2026-11-27T14:57:00+08:00",
               "2026-11-28T14:30:00+08:00", "2026-11-27T14:30:00",
               "2026-11-27T12:00:00+08:00"):
        with pytest.raises(ValueError):
            compare_intraday_t(account(), make(second=make().second.model_copy(update={"at": at})))


def test_missing_mark_preserves_paired_cash_delta_not_absolute_wealth():
    result = compare_intraday_t(account(), make(terminal_mark_at=None, terminal_mark_cny=None))
    assert result["positive_t"]["delta_vs_no_action_cny"] == "28.47"
    assert result["positive_t"]["terminal_equity_cny"] is None


@pytest.mark.parametrize("kwargs", [
    {"quantity": 150}, {"reference_close_cny": None},
    {"terminal_mark_at": "2026-11-27T10:30:00+08:00"},
    {"terminal_mark_cny": "11.01"},
])
def test_invalid_bounds_fail_closed(kwargs):
    with pytest.raises(ValueError):
        compare_intraday_t(account(), make(**kwargs))


def test_utc_and_shanghai_times_are_compared_as_instants():
    second = make().second.model_copy(update={"at": datetime.fromisoformat("2026-11-27T06:30:00+00:00").isoformat()})
    assert compare_intraday_t(account(), make(second=second))["positive_t"]["status"] == "PAIRED_CONDITIONAL"
