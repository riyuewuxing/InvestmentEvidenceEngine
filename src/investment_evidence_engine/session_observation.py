"""Pure mainland research-session boundaries; no claim of market data admission.

A scheduled label is not the actual observation time. Trading-day status must
come from a caller's calendar evidence; this module does not infer it.
"""
from __future__ import annotations

from datetime import date, datetime, time
from math import isfinite
from zoneinfo import ZoneInfo

SH = ZoneInfo("Asia/Shanghai")
WINDOWS = {
    "PREMARKET": (time(8, 30), time(9, 15)),
    "OPEN_AUCTION": (time(9, 26), time(9, 30)),
    "EOD": (time(14, 30), time(15)),
    "POST_CLOSE": (time(15), time(23, 59, 59, 999999)),
}


def session_window_status(stage: str, *, session: date, started_at: datetime,
                          finished_at: datetime, trading_day: bool | None) -> str:
    if stage not in WINDOWS or type(session) is not date:
        raise ValueError("SESSION_SCOPE")
    if started_at.utcoffset() is None or finished_at.utcoffset() is None or finished_at < started_at:
        return "INVALID_CLOCK"
    if trading_day is not True:
        return "NON_TRADING_DAY" if trading_day is False else "CALENDAR_UNKNOWN"
    start, end = started_at.astimezone(SH), finished_at.astimezone(SH)
    if start.date() != session or end.date() != session:
        return "SESSION_MISMATCH"
    lo, hi = WINDOWS[stage]
    if start.time() < lo:
        return "TOO_EARLY"
    if start.time() >= hi or end.time() >= hi:
        return "WINDOW_MISSED"
    return "WITHIN_WINDOW"


def auction_reference_status(*, session: date, market_at: datetime | None,
                             retrieved_at: datetime | None, cutoff: datetime,
                             trading_day: bool | None) -> str:
    """Opening uncrossing reference only; no availability/eligibility claim."""
    if cutoff.utcoffset() is None:
        return "INVALID_CLOCK"
    if trading_day is not True:
        return "NON_TRADING_DAY" if trading_day is False else "CALENDAR_UNKNOWN"
    if market_at is None or retrieved_at is None or market_at.utcoffset() is None or retrieved_at.utcoffset() is None:
        return "SOURCE_TIME_UNKNOWN"
    if not market_at <= retrieved_at <= cutoff:
        return "AFTER_CUTOFF_OR_INVALID_ORDER"
    m, r, c = (x.astimezone(SH) for x in (market_at, retrieved_at, cutoff))
    if any(x.date() != session for x in (m, r, c)):
        return "SESSION_MISMATCH"
    # The final opening-auction result is not a 09:20 indicative price or
    # a 09:30 continuous-trading quote. Source semantics must also be verified.
    if not time(9, 25) <= m.time() < time(9, 30):
        return "NOT_AUCTION_RESULT_TIME"
    if not time(9, 26) <= c.time() < time(9, 30):
        return "OUTSIDE_AUCTION_REVIEW_WINDOW"
    return "CHRONOLOGY_ONLY"


def pool_count(value: object) -> int | None:
    """None or schema-less objects are not a verified empty pool."""
    if value is None or not hasattr(value, "columns") or not hasattr(value, "empty"):
        return None
    return len(value)


def advance_ratio(up: object, down: object, flat: object) -> float | None:
    values = (up, down, flat)
    if any(type(x) not in (int, float) or not isfinite(x) or x < 0 for x in values):
        return None
    total = sum(values)
    return up / total * 100 if total > 0 else None
