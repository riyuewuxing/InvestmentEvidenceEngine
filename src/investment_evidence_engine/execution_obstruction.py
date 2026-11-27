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
ST_LIMIT_CHANGE = date(2026, 7, 6)


def tick_price(value: str) -> Decimal:
    if type(value) is not str or not 0 < len(value) <= 24 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
        raise ValueError("PRICE_TYPE")
    x = Decimal(value)
    with localcontext() as ctx:
        ctx.prec = 32
        if not TICK <= x <= Decimal("1000000") or x != x.quantize(TICK):
            raise ValueError("PRICE_NOT_POSITIVE_CENT")
    return x


def conditional_limits(reference: Decimal, rate: Decimal) -> tuple[Decimal, Decimal]:
    if type(rate) is not Decimal or rate not in {Decimal('0.05'), Decimal('0.10')}:
        raise ValueError('UNSUPPORTED_LIMIT_RATE')
    reference = tick_price(str(reference))
    with localcontext() as ctx:
        ctx.prec = 32
        up = (reference * (1 + rate)).quantize(TICK, rounding=ROUND_HALF_UP)
        down = (reference * (1 - rate)).quantize(TICK, rounding=ROUND_HALF_UP)
        return max(TICK, min(down, reference - TICK)), max(up, reference + TICK)


def ordinary_limits(reference: Decimal) -> tuple[Decimal, Decimal]:
    return conditional_limits(reference, Decimal("0.10"))


def inspect_explicit_eligibility(rows: list, *, identity: str, sessions: tuple[date, ...],
                                 regimes: dict[date, str], other_ohlc: dict[date, tuple],
                                 event_references: dict[date, Decimal]) -> dict:
    """Exact historical day-status diagnostic, with no inferred missing session.

    Regimes are explicit issuer-derived assumptions for the whole window.
    Suspended rows must be represented by a vendor status, not fabricated
    from the absence of a bar. No market execution, queuing or PIT claim.
    """
    if (not isinstance(identity, str) or not re.fullmatch(r"sz\.(?:000|001|002|003)[0-9]{3}", identity)
            or not isinstance(sessions, tuple) or len(sessions) < 3 or any(type(d) is not date for d in sessions)
            or sessions != tuple(sorted(set(sessions))) or sessions[0] < REVIEWED_START
            or sessions[-1] > REVIEWED_END):
        raise ValueError("ELIGIBILITY_SCOPE")
    expected = tuple(r.day for r in scheduled_days(sessions[0], sessions[-1]) if r.is_trading_day)
    if (sessions != expected or not isinstance(rows, list) or len(rows) != len(sessions)
            or not isinstance(regimes, dict) or set(regimes) != set(sessions)
            or any(type(k) is not date or v not in {"ST_5", "ST_10", "ORDINARY_10", "SUSPENDED"} for k, v in regimes.items())
            or not isinstance(other_ohlc, dict) or not isinstance(event_references, dict)):
        raise ValueError("ELIGIBILITY_COVERAGE")
    trading = {d for d in sessions if regimes[d] != "SUSPENDED"}
    if not trading or any((regimes[d] == "ST_5" and d >= ST_LIMIT_CHANGE)
                          or (regimes[d] == "ST_10" and d < ST_LIMIT_CHANGE) for d in trading):
        raise ValueError("ELIGIBILITY_RULE_DATE_SCOPE")
    if set(other_ohlc) != trading:
        raise ValueError("ELIGIBILITY_OTHER_SOURCE_COVERAGE")
    if (not set(event_references) <= trading - {min(trading)}
            or any(type(d) is not date or type(v) is not Decimal for d, v in event_references.items())):
        raise ValueError("ELIGIBILITY_REFERENCE_SCOPE")
    for value in event_references.values():
        tick_price(str(value))
    audit = []
    previous = None
    for day, row in zip(sessions, rows, strict=True):
        if (not isinstance(row, (tuple, list)) or len(row) != 11 or any(type(v) is not str for v in row)
                or row[0] != day.isoformat() or row[1] != identity or row[8] != "3"
                or row[9] not in {"0", "1"}):
            raise ValueError("ELIGIBILITY_ROW_SCHEMA_OR_IDENTITY")
        regime = regimes[day]
        # Some suspended rows contain no volume or ST field. Preserve the
        # missingness; only an explicit suspension flag plus the reviewed
        # regime and independent absence of a trade bar can exclude the day.
        if row[7] == "":
            volume = None
        else:
            if not re.fullmatch(r"[0-9]{1,20}(?:\.[0-9]{1,8})?", row[7]):
                raise ValueError("ELIGIBILITY_VOLUME")
            volume = Decimal(row[7])
            if volume != volume.to_integral_value():
                raise ValueError("ELIGIBILITY_VOLUME")
        if regime == "SUSPENDED":
            if row[9] != "0" or volume not in (None, Decimal(0)) or row[10] not in ("", "0", "1"):
                raise ValueError("ELIGIBILITY_SUSPENSION_CONFLICT")
            audit.append({"day": day.isoformat(), "status": "SUSPENDED_NOT_TRADE_ELIGIBLE",
                          "vendor_st_flag": row[10] or None,
                          "volume_observation": "MISSING_NOT_IMPUTED" if volume is None else "OBSERVED_ZERO",
                          "trade_price_inferred": False})
            continue
        if row[9] != "1" or volume is None or volume <= 0 or row[10] != ("1" if regime in {"ST_5", "ST_10"} else "0"):
            raise ValueError("ELIGIBILITY_ST_OR_TRADE_FLAG_CONFLICT")
        opening, high, low, close, ref = map(tick_price, row[2:7])
        other = other_ohlc[day]
        if (not isinstance(other, tuple) or len(other) != 4 or any(type(x) is not Decimal for x in other)
                or tuple(map(tick_price, map(str, other))) != (opening, high, low, close)):
            raise ValueError("ELIGIBILITY_OHLC_CROSSCHECK")
        if previous is not None and ref != event_references.get(day, previous):
            raise ValueError("ELIGIBILITY_UNRECONCILED_REFERENCE")
        rate = Decimal("0.05") if regime == "ST_5" else Decimal("0.10")
        down, up = conditional_limits(ref, rate)
        if not down <= low <= min(opening, close) <= max(opening, close) <= high <= up:
            raise ValueError("ELIGIBILITY_LIMIT_OR_OHLC_CONFLICT")
        audit.append({"day": day.isoformat(), "status": "OBSERVED_TRADING_DAY_CONDITIONAL_LIMIT",
                      "limit_rate": str(rate), "previous_reference": str(ref), "close": str(close),
                      "lower": str(down), "upper": str(up), "open_at_upper": opening == up,
                      "open_at_lower": opening == down,
                      "one_price_upper": high == low == up, "one_price_lower": high == low == down})
        previous = close
    return {"status": "CONDITIONAL_EXPLICIT_DAY_ELIGIBILITY_ONLY", "subject": identity,
            "sessions": len(sessions), "trading_sessions": len(trading),
            "suspended_sessions": len(sessions) - len(trading), "audit": audit,
            "first_prior_reference_verified": False, "historical_vintage_verified": False,
            "exceptional_regimes_exhaustively_verified": False, "actual_order_fills_verified": False,
            "decision_authority": False, "execution_allowed": False, "pit_safe": False}


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
