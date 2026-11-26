"""Pure numeric guard for already selected, visible price-adjustment factors.

Caller owns the time/source selection. This guard cannot certify source vintage.
A factor id or a corporate-action id may contribute at most once.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from numbers import Real


def positive_finite(value: object) -> bool:
    if not isinstance(value, Real) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value)) and value > 0
    except (OverflowError, ValueError):
        return False


def checked_adjusted_close(raw_close: float,
                           factors: Iterable[tuple[str, str, float]]) -> float:
    """Apply each distinct action once, rejecting ambiguous revisions and bad arithmetic."""
    if not positive_finite(raw_close):
        raise ValueError("ADJUSTMENT_RAW_CLOSE_INVALID")
    multiplier = 1.0
    seen_factors: set[str] = set()
    seen_actions: set[str] = set()
    for factor_id, action_id, factor in factors:
        if not all(isinstance(x, str) and x and x == x.strip()
                   for x in (factor_id, action_id)):
            raise ValueError("ADJUSTMENT_IDENTITY_INVALID")
        if factor_id in seen_factors or action_id in seen_actions:
            raise ValueError("ADJUSTMENT_DUPLICATE_OR_UNRESOLVED_REVISION")
        if not positive_finite(factor):
            raise ValueError("ADJUSTMENT_FACTOR_INVALID")
        seen_factors.add(factor_id)
        seen_actions.add(action_id)
        multiplier *= factor
        if not positive_finite(multiplier):
            raise ValueError("ADJUSTMENT_MULTIPLIER_NONFINITE_OR_NONPOSITIVE")
    close = raw_close * multiplier
    if not positive_finite(close):
        raise ValueError("ADJUSTMENT_RESULT_NONFINITE_OR_NONPOSITIVE")
    return close
