"""Small generic numeric evidence guards.

Missing or invalid input is not zero. A known threshold violation can still
be surfaced despite another missing observation. No decision authority.
"""
from __future__ import annotations

import math


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
