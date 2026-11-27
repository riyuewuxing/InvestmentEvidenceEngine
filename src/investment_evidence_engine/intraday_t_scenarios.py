"""Read-only equal-quantity positive/reverse T scenarios versus no action.

All prices, fill outcomes, exchange state and fees are explicit assumptions.
This never infers fills from a minute bar, a single quote, or a price crossing.
New purchases do not replenish the old sellable inventory on the same day.
Only the selected holding and available cash are marked, not the full portfolio.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal, localcontext
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from .cash_execution_math import canonical_cent, order_fees, price_band

SH = ZoneInfo("Asia/Shanghai")
D0 = Decimal(0)
CENT = Decimal("0.01")
Fill = Literal["ASSUME_FILLED", "ASSUME_NOT_FILLED", "UNKNOWN"]
MarketState = Literal["ASSUMED_OPEN", "ASSUMED_SUSPENDED", "UNKNOWN"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class FeeAssumptions(Strict):
    commission_rate: str
    minimum_commission_cny: str
    transfer_rate: str
    sell_stamp_rate: str


class TLeg(Strict):
    at: str
    buy_price_cny: str | None = None
    sell_price_cny: str | None = None
    buy_fill: Fill = "UNKNOWN"
    sell_fill: Fill = "UNKNOWN"
    market_state: MarketState = "UNKNOWN"


class TScenario(Strict):
    session_date: str
    calendar_state: Literal["ASSUMED_TRADING_DAY", "NON_TRADING_DAY", "UNKNOWN"]
    reference_close_cny: str | None = None
    limit_rate: str | None = None
    minimum_buy_units: int = Field(ge=100, le=1000000)
    buy_increment: int = Field(ge=1, le=1000000)
    quantity: int = Field(ge=100, le=100000000)
    first: TLeg
    second: TLeg
    terminal_mark_cny: str | None = None
    terminal_mark_at: str | None = None
    fees: FeeAssumptions | None = None


class TAccountReference(Strict):
    cash_cny: str
    held_units: int = Field(ge=0, le=1000000000)
    sellable_old_units: int | None = Field(default=None, ge=0, le=1000000000)


def _decimal(value: str, *, maximum: Decimal, cent: bool = False, positive: bool = False) -> Decimal:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,16}(?:\.[0-9]{1,8})?", value):
        raise ValueError("T_DECIMAL_FORMAT")
    number = Decimal(value)
    if number > maximum or (positive and number == 0) or (cent and number != number.quantize(CENT)):
        raise ValueError("T_DECIMAL_SCOPE")
    return number


def _stamp(value: str, session: date, *, mark: bool = False) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("T_EXACT_CLOCK_REQUIRED")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.utcoffset() is None:
        raise ValueError("T_EXACT_CLOCK_REQUIRED")
    local = stamp.astimezone(SH)
    clock = local.time()
    # Conservative continuous-trading reference, not auction/closing auction.
    valid = time(9, 30) <= clock < time(11, 30) or time(13) <= clock < time(14, 57)
    if mark:
        valid = time(9, 30) <= clock <= time(11, 30) or time(13) <= clock <= time(15)
    if local.date() != session or not valid:
        raise ValueError("T_SESSION_OR_WINDOW")
    return local


def _price(value: str | None) -> Decimal | None:
    if value is None:
        return None
    return canonical_cent(_decimal(value, maximum=Decimal("1000000"), cent=True, positive=True))


def _money(value: Decimal | None) -> str | None:
    return None if value is None else format(value.quantize(CENT), "f")


def compare_intraday_t(account: TAccountReference, scenario: TScenario) -> dict:
    account = TAccountReference.model_validate(account.model_dump())
    scenario = TScenario.model_validate(scenario.model_dump())
    day = date.fromisoformat(scenario.session_date)
    if day.isoformat() != scenario.session_date:
        raise ValueError("T_SESSION_FORMAT")
    first = _stamp(scenario.first.at, day)
    second = _stamp(scenario.second.at, day)
    if second <= first:
        raise ValueError("T_LEG_ORDER")
    if (scenario.terminal_mark_cny is None) != (scenario.terminal_mark_at is None):
        raise ValueError("T_TERMINAL_MARK_SCOPE")
    mark = _price(scenario.terminal_mark_cny)
    if scenario.terminal_mark_at is not None and _stamp(scenario.terminal_mark_at, day, mark=True) < second:
        raise ValueError("T_MARK_BEFORE_SECOND_LEG")
    if (scenario.reference_close_cny is None) != (scenario.limit_rate is None):
        raise ValueError("T_PRICE_BAND_SCOPE")
    band = None
    if scenario.reference_close_cny is not None:
        rate = _decimal(scenario.limit_rate, maximum=Decimal("0.99"), positive=True)
        band = price_band(_price(scenario.reference_close_cny), rate)

    qty = scenario.quantity
    if qty < scenario.minimum_buy_units or (qty - scenario.minimum_buy_units) % scenario.buy_increment:
        raise ValueError("T_EQUAL_QUANTITY_LOT_INVALID")
    cash = _decimal(account.cash_cny, maximum=Decimal("1e13"), cent=True)
    held, old = account.held_units, account.sellable_old_units
    if old is not None and old > held:
        raise ValueError("T_SELLABLE_EXCEEDS_HOLDING")
    prices = tuple((_price(x.buy_price_cny), _price(x.sell_price_cny)) for x in (scenario.first, scenario.second))
    for buy, sell in prices:
        if buy is not None and sell is not None and sell > buy:
            raise ValueError("T_CROSSED_ASSUMED_QUOTES")
    if band and any(not band[0] <= p <= band[1] for p in (*prices[0], *prices[1], mark) if p is not None):
        raise ValueError("T_PRICE_OUTSIDE_ASSUMED_BAND")
    fees = None
    if scenario.fees is not None:
        f = scenario.fees
        fees = dict(commission_rate=_decimal(f.commission_rate, maximum=Decimal("0.1")),
                    minimum_commission=_decimal(f.minimum_commission_cny, maximum=Decimal("100000"), cent=True),
                    transfer_rate=_decimal(f.transfer_rate, maximum=Decimal("0.1")),
                    sell_stamp_rate=_decimal(f.sell_stamp_rate, maximum=Decimal("0.1")))

    baseline = None if mark is None else cash + held * mark
    common = {
        "session_date": day.isoformat(), "scope": "SELECTED_HOLDING_AND_AVAILABLE_CASH_ONLY",
        "quantity": qty, "input_basis": "EXPLICIT_CONDITIONAL_ASSUMPTIONS_NOT_OBSERVED_FILLS",
        "price_band_cny": [_money(x) for x in band] if band else None,
        "terminal_mark_cny": _money(mark), "terminal_mark_at": scenario.terminal_mark_at,
        "actual_fills_verified": False, "actual_broker_fees_verified": False,
        "source_time_verified": False, "exchange_calendar_verified": False,
        "account_authentication_verified": False, "probability_estimated": False,
        "expected_return_estimated": False, "formal_marginal_risk_estimated": False,
        "decision_authority": False, "research_only": True, "execution_allowed": False,
    }

    def terminal(status, reason, steps, state, *, paired=False):
        row = {"status": status, "reason": reason, "legs": steps,
               "terminal_cash_cny": None, "terminal_held_units": None,
               "terminal_sellable_old_units": None, "terminal_new_locked_units": None,
               "terminal_equity_cny": None, "delta_vs_no_action_cny": None,
               "matched_net_cash_delta_cny": None, "position_delta_units": None}
        if state is not None:
            c, h, s, locked = state
            equity = None if mark is None else c + h * mark
            delta = c - cash if h == held else None if mark is None else (c - cash) + (h - held) * mark
            row.update(terminal_cash_cny=_money(c), terminal_held_units=h, terminal_sellable_old_units=s,
                       terminal_new_locked_units=locked, terminal_equity_cny=_money(equity),
                       delta_vs_no_action_cny=_money(delta), position_delta_units=h-held,
                       matched_net_cash_delta_cny=_money(c-cash) if paired else None)
        return row

    initial = (cash, held, old, 0)

    def leg(index, side, state):
        opportunity = (scenario.first, scenario.second)[index]
        c, h, s, locked = state
        is_buy = side == "BUY"
        price = prices[index][0 if is_buy else 1]
        outcome = opportunity.buy_fill if is_buy else opportunity.sell_fill
        step = {"side": side, "at": opportunity.at, "assumed_price_cny": _money(price),
                "quantity": qty, "fee_cny": None, "notional_cny": None}
        if opportunity.market_state == "ASSUMED_SUSPENDED":
            return step | {"status": "NOT_FILLED_CONDITIONAL", "reason": "ASSUMED_SUSPENSION"}, state
        if opportunity.market_state == "UNKNOWN":
            return step | {"status": "UNKNOWN", "reason": "MARKET_STATE_UNKNOWN"}, None
        if outcome == "ASSUME_NOT_FILLED":
            return step | {"status": "NOT_FILLED_CONDITIONAL", "reason": "EXPLICIT_NO_FILL"}, state
        if price is None:
            return step | {"status": "UNKNOWN", "reason": "LEG_PRICE_UNKNOWN"}, None
        notional = price * qty
        fee = order_fees(notional, side=side, **fees).total
        if is_buy and c < notional + fee:
            return step | {"status": "BLOCKED_CONDITIONAL", "reason": "INSUFFICIENT_CASH_INCLUDING_FEES"}, state
        if not is_buy and (s < qty or c + notional - fee < 0):
            return step | {"status": "BLOCKED_CONDITIONAL", "reason": "INSUFFICIENT_OLD_SELLABLE_OR_CASH"}, state
        if (is_buy and price == band[1]) or (not is_buy and price == band[0]):
            return step | {"status": "UNKNOWN", "reason": "ADVERSE_LIMIT_QUEUE_UNVERIFIED"}, None
        if outcome != "ASSUME_FILLED":
            return step | {"status": "UNKNOWN", "reason": "LEG_FILL_UNKNOWN"}, None
        new = (c-notional-fee, h+qty, s, locked+qty) if is_buy else (c+notional-fee, h-qty, s-qty, locked)
        return step | {"status": "ASSUMED_FILLED_NOT_ACTUAL", "reason": "EXPLICIT_HYPOTHESIS",
                       "fee_cny": _money(fee), "notional_cny": _money(notional)}, new

    def branch(order):
        if scenario.calendar_state == "NON_TRADING_DAY":
            return terminal("BLOCKED_BEFORE_FIRST", "NON_TRADING_DAY", [], initial)
        if scenario.calendar_state != "ASSUMED_TRADING_DAY":
            return terminal("UNKNOWN_BEFORE_FIRST", "CALENDAR_UNKNOWN", [], None)
        if old is None:
            return terminal("UNKNOWN_BEFORE_FIRST", "OLD_SELLABLE_UNKNOWN", [], None)
        if qty > old:
            return terminal("BLOCKED_BEFORE_FIRST", "PAIRED_T_REQUIRES_OLD_SELLABLE", [], initial)
        if band is None or fees is None:
            return terminal("UNKNOWN_BEFORE_FIRST", "PRICE_BAND_OR_FEES_UNKNOWN", [], None)
        one, state = leg(0, order[0], initial)
        if state is None:
            return terminal("UNKNOWN_FIRST_LEG", one["reason"], [one], None)
        if one["status"] != "ASSUMED_FILLED_NOT_ACTUAL":
            return terminal("NO_FIRST_FILL_CONDITIONAL", one["reason"], [one], state)
        two, final = leg(1, order[1], state)
        if final is None:
            row = terminal("UNKNOWN_SECOND_LEG", two["reason"], [one, two], None)
            row["conditional_state_after_first"] = {
                "cash_cny": _money(state[0]), "held_units": state[1],
                "sellable_old_units": state[2], "new_locked_units": state[3]}
            return row
        if two["status"] != "ASSUMED_FILLED_NOT_ACTUAL":
            return terminal("UNPAIRED_CONDITIONAL", two["reason"], [one, two], final)
        return terminal("PAIRED_CONDITIONAL", "BOTH_LEGS_EXPLICITLY_ASSUMED", [one, two], final, paired=True)

    with localcontext() as ctx:
        ctx.prec = 48
        return common | {
            "no_action": {"status": "REFERENCE_ONLY", "terminal_cash_cny": _money(cash),
                          "terminal_held_units": held, "terminal_sellable_old_units": old,
                          "terminal_equity_cny": _money(baseline), "delta_vs_no_action_cny": "0.00"},
            "positive_t": branch(("BUY", "SELL")), "reverse_t": branch(("SELL", "BUY")),
        }
