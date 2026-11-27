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


def quote_reference_status(*, session: date, market_at: datetime | None,
                           retrieved_at: datetime, max_age_seconds: int = 120) -> str:
    """Same-day quote chronology and bounded age, not execution or source admission."""
    if (market_at is None or market_at.utcoffset() is None
            or retrieved_at.utcoffset() is None or max_age_seconds < 0):
        return "QUOTE_TIME_UNKNOWN"
    m, r = market_at.astimezone(SH), retrieved_at.astimezone(SH)
    if m.date() != session or r.date() != session:
        return "QUOTE_SESSION_MISMATCH"
    if not time(14, 30) <= m.time() < time(15):
        return "QUOTE_OUTSIDE_TAIL"
    age = (r - m).total_seconds()
    if age < 0:
        return "QUOTE_AFTER_RETRIEVAL"
    if age > max_age_seconds:
        return "QUOTE_STALE"
    return "CHRONOLOGY_ONLY"


def _finite(value: object) -> float | None:
    if type(value) not in (int, float) or not isfinite(value):
        return None
    return float(value)


def structure_filter_status(metrics: dict, filters: dict) -> str:
    """Filter a bounded observation, with frontend-equivalent comparison rules.

    No default is substituted for a missing configured metric. The main-flow
    field must already be scope-checked by the caller.
    """
    checks = (
        ("timeline_above_avg_ratio", "timeline_above_avg_ratio", False),
        ("tail_30m_return_pct", "tail_30m_slope_min", False),
        ("tail_30m_amount_share_pct", "tail_30m_amount_share_min", False),
        ("intraday_drawback_pct", "intraday_drawback_max", True),
    )
    failed = False
    unknown = False
    for metric, key, upper in checks:
        threshold = filters[key]
        if threshold is None:
            if key == "timeline_above_avg_ratio":
                raise ValueError("TIMELINE_THRESHOLD_REQUIRED")
            continue
        limit = _finite(threshold)
        if limit is None:
            raise ValueError("STRUCTURE_THRESHOLD_INVALID")
        value = _finite(metrics.get(metric))
        if value is None:
            unknown = True
        elif (value > limit if upper else value < limit):
            failed = True
    if filters["require_main_inflow"] is True:
        flow = _finite(metrics.get("main_net_inflow_10k"))
        unknown |= flow is None
        failed |= flow is not None and flow <= 0
    elif filters["require_main_inflow"] is not False:
        raise ValueError("STRUCTURE_FLOW_FILTER_INVALID")
    return "EXCLUDED" if failed else "UNAVAILABLE" if unknown else "MATCH"


def dated_daily_flow_reference(rows: list[dict], *, session: date, cutoff: datetime) -> tuple[float | None, str]:
    """Current dated daily close reference, never a 14:45 intraday flow value.

    The provider has date labels rather than a verified intraday observation
    clock. Do not use earlier/future rows as the requested day's flow or
    assume the latest element is the latest valid observation.
    """
    if cutoff.utcoffset() is None or cutoff.astimezone(SH).date() != session:
        return None, "FLOW_CUTOFF_SCOPE"
    if cutoff.astimezone(SH).time() < time(15):
        return None, "DAILY_FLOW_NOT_INTRADAY"
    values = []
    for row in rows:
        if row.get("date") != session.isoformat():
            continue
        value_yuan = _finite(row.get("mainNetInflowYuan"))
        value_wan = _finite(row.get("mainNetInflowWan"))
        legacy = _finite(row.get("mainNetInflow"))
        if value_yuan is not None and value_wan is not None:
            if abs(value_yuan / 10000 - value_wan) > 1e-8:
                return None, "FLOW_UNIT_CONFLICT"
        value = value_yuan / 10000 if value_yuan is not None else value_wan
        if value is None and legacy is not None:
            # Existing daily-provider contract is yuan. Generic netInflow
            # without a declared main-flow field is deliberately not accepted.
            value = legacy / 10000
        if value is None:
            return None, "FLOW_VALUE_UNKNOWN"
        values.append(value)
    if not values:
        return None, "FLOW_SESSION_UNAVAILABLE"
    if len(set(values)) != 1:
        return None, "FLOW_DUPLICATE_CONFLICT"
    return values[0], "DATED_DAILY_REFERENCE_ONLY"
