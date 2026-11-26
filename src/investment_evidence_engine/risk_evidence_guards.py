"""Small generic numeric evidence guards.

Missing or invalid input is not zero. A known threshold violation can still
be surfaced despite another missing observation. No decision authority.
"""
from __future__ import annotations

import math
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo


def finite(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def complete_nonnegative_sum(values: tuple[float | None, ...]) -> float | None:
    nums = tuple(finite(v) for v in values)
    if not nums or any(v is None or v < 0 for v in nums):
        return None
    return finite(sum(nums))


def complete_nonnegative_max(values: tuple[float | None, ...]) -> float | None:
    nums = tuple(finite(v) for v in values)
    if not nums or any(v is None or v < 0 for v in nums):
        return None
    return max(nums)


def growth_pct(current: float | None, previous: float | None) -> float | None:
    cur, prev = finite(current), finite(previous)
    if cur is None or prev is None or cur < 0 or prev <= 0:
        return None
    return finite((cur-prev)/prev*100)


def high_risk(checks: tuple[tuple[float | None, float, float], ...]) -> str:
    """Strict greater-than thresholds; known warnings do not erase missing data."""
    if not checks:
        raise ValueError("at least one check required")
    missing = warning = red = False
    for value, warn, severe in checks:
        if finite(warn) is None or finite(severe) is None or warn >= severe:
            raise ValueError("invalid thresholds")
        number = finite(value)
        if number is None:
            missing = True
        elif number > severe:
            red = True
        elif number > warn:
            warning = True
    if red:
        return "RED_FLAG"
    if warning:
        return "WARN"
    return "UNKNOWN" if missing else "PASS"


def aggregate_status(statuses: tuple[str, ...]) -> str:
    if not statuses or any(s not in {"RED_FLAG", "WARN", "UNKNOWN", "PASS"} for s in statuses):
        raise ValueError("invalid risk status set")
    for status in ("RED_FLAG", "WARN", "UNKNOWN"):
        if status in statuses:
            return status
    return "CLEAN"


def period_day(value: object, *, cutoff: date | None = None) -> str | None:
    """Parse only explicit date/ISO datetime labels; never infer a missing period."""
    raw = str(value).strip() if value is not None else ""
    try:
        if len(raw) == 8 and raw.isascii() and raw.isdigit():
            day = date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
        elif len(raw) == 10:
            day = date.fromisoformat(raw)
        elif len(raw) > 10 and raw[10] in "T ":
            day = datetime.fromisoformat(raw).date()
        else:
            return None
    except (ValueError, OverflowError):
        return None
    if cutoff is not None and day > cutoff:
        return None
    return day.isoformat()


def aligned_period_indices(values: tuple[object, ...], *, cutoff: date,
                           anchor: str | None = None) -> tuple[tuple[int, ...], str | None]:
    """Exact one current row; keep older duplicates visible to comparison guards."""
    days = tuple(period_day(v, cutoff=cutoff) for v in values)
    observed = [d for d in days if d is not None]
    selected = anchor or (max(observed) if observed else None)
    if selected is None or days.count(selected) != 1:
        return (), anchor
    idx = tuple(sorted((i for i, d in enumerate(days) if d is not None and d <= selected),
                       key=lambda i: days[i], reverse=True))
    return idx, selected


def fresh_observation_epoch(fetched: object, now: object, *, ttl_seconds: float) -> bool:
    first, last = finite(fetched), finite(now)
    ttl = finite(ttl_seconds)
    if (first is None or last is None or ttl is None or first <= 0 or ttl <= 0
            or not 0 <= last-first < ttl):
        return False
    try:
        tz = ZoneInfo("Asia/Shanghai")
        return (datetime.fromtimestamp(first, UTC).astimezone(tz).date()
                == datetime.fromtimestamp(last, UTC).astimezone(tz).date())
    except (OSError, ValueError, OverflowError):
        return False
