"""Narrow, retrospective ordinary Shenzhen main-board limit diagnostic.

No order fills, no PIT assurance, no account or executable recommendation.
A price at a limit is not proof that any particular order could not fill.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext

from .market_calendar import scheduled_days
from .momentum_profile import WINDOW, momentum_profile

TICK = Decimal("0.01")
RULES = (
    "https://docs.static.szse.cn/www/lawrules/rule/allrules/bussiness/W020230217564423808793.pdf",
    "https://docs.static.szse.cn/www/lawrules/rule/trade/W020260424690713155663.pdf",
)
REVIEWED_START = date(2025, 1, 2)
REVIEWED_END = date(2026, 11, 25)


def tick_price(value: str) -> Decimal:
    if type(value) is not str or not 0 < len(value) <= 24 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
        raise ValueError("PRICE_TYPE")
    x = Decimal(value)
    with localcontext() as ctx:
        ctx.prec = 32
        if not TICK <= x <= Decimal("1000000") or x != x.quantize(TICK):
            raise ValueError("PRICE_NOT_POSITIVE_CENT")
    return x


def ordinary_limits(reference: Decimal) -> tuple[Decimal, Decimal]:
    reference = tick_price(str(reference))
    with localcontext() as ctx:
        ctx.prec = 32
        up = (reference * Decimal("1.10")).quantize(TICK, rounding=ROUND_HALF_UP)
        down = (reference * Decimal("0.90")).quantize(TICK, rounding=ROUND_HALF_UP)
        return max(TICK, min(down, reference - TICK)), max(up, reference + TICK)


def inspect_status_rows(rows: list, *, identity: str, sessions: tuple[date, ...],
                        event_references: dict[date, Decimal]) -> dict:
    """Reject unsupported regime or inconsistency; never impute missing days."""
    if (not identity.startswith(("sz.000", "sz.001", "sz.002", "sz.003"))
            or len(identity) != 9 or not identity[3:].isdigit()
            or not isinstance(sessions, tuple) or not sessions or any(type(d) is not date for d in sessions)
            or sessions != tuple(sorted(set(sessions)))
            or sessions[0] < REVIEWED_START or sessions[-1] > REVIEWED_END):
        raise ValueError("UNSUPPORTED_SCOPE")
    expected_sessions = tuple(r.day for r in scheduled_days(sessions[0], sessions[-1]) if r.is_trading_day)
    if sessions != expected_sessions or len(rows) != len(sessions):
        raise ValueError("STATUS_COVERAGE")
    if (not isinstance(event_references, dict) or not set(event_references) <= set(sessions[1:])
            or any(type(d) is not date or type(v) is not Decimal for d, v in event_references.items())):
        raise ValueError("EVENT_SCOPE")
    for value in event_references.values():
        tick_price(str(value))
    bars = []
    for i, (day, row) in enumerate(zip(sessions, rows, strict=True)):
        if (not isinstance(row, (list, tuple)) or len(row) != 11 or any(type(v) is not str for v in row)
                or row[0] != day.isoformat() or row[1] != identity or row[8] != "3"):
            raise ValueError("STATUS_IDENTITY_DATE_BASIS")
        if row[9] != "1" or row[10] != "0":
            raise ValueError("NONORDINARY_OR_UNKNOWN_DAILY_STATUS")
        opening, high, low, close, ref = map(tick_price, row[2:7])
        if not 0 < len(row[7]) <= 32 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", row[7]):
            raise ValueError("VOLUME_INVALID")
        volume = Decimal(row[7])
        if volume <= 0 or volume != volume.to_integral_value():
            raise ValueError("VOLUME_INVALID")
        if i and ref != event_references.get(day, bars[-1]["close"]):
            raise ValueError("UNRECONCILED_DAILY_REFERENCE")
        down, up = ordinary_limits(ref)
        if not down <= low <= min(opening, close) <= max(opening, close) <= high <= up:
            raise ValueError("CONDITIONAL_LIMIT_OR_OHLC_MISMATCH")
        bars.append({"date": day, "open": opening, "high": high, "low": low,
                     "close": close, "reference": ref, "down": down, "up": up})
    # Use the existing profile's exact split boundaries, not a new strategy.
    profile = momentum_profile(sessions, [float(b["close"]) for b in bars],
                               [float(b["open"]) for b in bars])
    segments = []
    index = {day.isoformat(): i for i, day in enumerate(sessions)}
    for segment in profile["segments"]:
        start = index[segment["first_entry_open"]]
        terminal = index[segment["terminal_open"]]
        old = 0
        transitions = []
        for t in range(start, terminal + 1):
            target = int(bars[t-1]["close"] > bars[t-1-WINDOW]["close"]) if t < terminal else 0
            if target == old:
                continue
            side = "BUY" if target > old else "SELL"
            bar = bars[t]
            limit = bar["up"] if side == "BUY" else bar["down"]
            at_limit = bar["open"] == limit
            locked = bar["high"] == bar["low"] == limit
            transitions.append({"day": bar["date"].isoformat(), "side": side,
                                "open_at_adverse_limit": at_limit,
                                "full_day_one_price_at_adverse_limit": locked})
            # Intended path only, not simulated successful fills.
            old = target
        expected = segment["stress"][0]["signal_rule"]["unit_weight_turnover"]
        if len(transitions) != expected:
            raise ValueError("PROFILE_TURNOVER_MISMATCH")
        segments.append({"segment": segment["segment"], "intended_transitions": len(transitions),
                         "open_adverse_limit_count": sum(r["open_at_adverse_limit"] for r in transitions),
                         "full_day_adverse_one_price_count": sum(
                             r["full_day_one_price_at_adverse_limit"] for r in transitions),
                         "flagged_intents": [r for r in transitions if r["open_at_adverse_limit"]]})
    return {"status": "CONDITIONAL_ORDINARY_LIMIT_DIAGNOSTIC", "sessions": len(bars),
            "segments": segments, "ordinary_limit_assumption": True,
            "exceptional_limit_regimes_independently_verified": False,
            "first_reference_prior_session_verified": False,
            "actual_order_fills_verified": False, "historical_vintage_verified": False,
            "decision_authority": False, "execution_allowed": False,
            "rule_locators": list(RULES), "rule_original_bytes_retained": False}
