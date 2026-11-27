"""Select one visible index observation cohort, never merge revisions.

This validates recorded times and a reported weight total, not source authenticity,
listing-instance identity, completeness, or continuous historical membership.
A common source_ref is necessary but not independent proof of an atomic capture.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from math import isfinite
from typing import Generic, Protocol, TypeVar


class ConstituentRow(Protocol):
    index_id: str
    effective_time: datetime
    available_at: datetime
    ingested_at: datetime
    security_id: str
    weight: float
    source_ref: str


Row = TypeVar("Row", bound=ConstituentRow)
WEIGHT_TOLERANCE = Decimal("0.0015")


@dataclass(frozen=True)
class CohortSelection(Generic[Row]):
    rows: tuple[Row, ...]
    status: str
    effective_time: datetime | None = None
    weight_sum: Decimal | None = None


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def select_constituent_cohort(
    rows: Iterable[Row], *, index_id: str, effective_at: datetime, cutoff: datetime,
) -> CohortSelection[Row]:
    """Return a single latest observed cohort or no usable rows.

    Source_ref must identify the same dataset for each row. If a visible new
    vintage is partial, inconsistent or ambiguous, do not fall back to an old
    vintage or fill removed names from it. Preannounced effective dates are
    allowed only when their observation is visible by the research cutoff.
    """
    if not _aware(effective_at) or not _aware(cutoff):
        return CohortSelection((), "INVALID_COHORT_CLOCK")
    visible = []
    for row in rows:
        if row.index_id != index_id:
            continue
        if not all(_aware(t) for t in (row.effective_time, row.available_at, row.ingested_at)):
            return CohortSelection((), "INVALID_COHORT_CLOCK")
        if row.available_at > row.ingested_at:
            return CohortSelection((), "INVALID_COHORT_CLOCK")
        if row.effective_time <= effective_at and row.ingested_at <= cutoff:
            visible.append(row)
    if not visible:
        return CohortSelection((), "NO_VISIBLE_COHORT")
    key = max((r.effective_time, r.available_at, r.ingested_at) for r in visible)
    cohort = tuple(r for r in visible if (r.effective_time, r.available_at, r.ingested_at) == key)
    refs = {r.source_ref for r in cohort}
    if len(refs) != 1 or not next(iter(refs)).strip():
        return CohortSelection((), "AMBIGUOUS_COHORT_SOURCE", key[0])
    if len({r.security_id for r in cohort}) != len(cohort) or any(not r.security_id.strip() for r in cohort):
        return CohortSelection((), "AMBIGUOUS_COHORT_MEMBER", key[0])
    if any(type(r.weight) not in (int, float) or not isfinite(r.weight)
           or not 0 <= r.weight <= 1 for r in cohort):
        return CohortSelection((), "INVALID_COHORT_WEIGHT", key[0])
    total = sum((Decimal(str(r.weight)) for r in cohort), Decimal(0))
    # Rounding tolerance is diagnostic only. A missing low-weight member can
    # satisfy it, so a successful result is not a complete membership claim.
    if abs(total - Decimal(1)) > WEIGHT_TOLERANCE:
        return CohortSelection((), "COHORT_WEIGHT_TOTAL_UNRECONCILED", key[0], total)
    return CohortSelection(tuple(sorted(cohort, key=lambda r: r.security_id)),
                           "POINT_COHORT_ONLY", key[0], total)
