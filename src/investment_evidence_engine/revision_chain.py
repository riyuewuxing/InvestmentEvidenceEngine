"""Explicit source revision lineage. Never select a revision by retrieval order.

A declared-release reconstruction and a system-observed view are different
queries. Even a fully checked chain does not prove completeness of all
historical versions, exact original dissemination, or decision admission.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .evidence_time_guard import aware


@dataclass(frozen=True)
class Revision:
    series_id: str
    period: str
    unit: str
    source_id: str
    revision_id: str
    predecessor_id: str | None
    value: Decimal
    predecessor_value: Decimal | None
    declared_release_at: datetime
    observed_at: datetime
    durable_verified_at: datetime
    raw_sha256: str

    def __post_init__(self):
        if not all(isinstance(v, str) and 0 < len(v) <= 200 and v.strip() == v
                   for v in (self.series_id, self.period, self.unit, self.source_id, self.revision_id)):
            raise ValueError("REVISION_IDENTITY_INVALID")
        if self.predecessor_id is not None and (
                not isinstance(self.predecessor_id, str) or not self.predecessor_id.strip()
                or self.predecessor_id == self.revision_id):
            raise ValueError("REVISION_PREDECESSOR_INVALID")
        if not isinstance(self.value, Decimal) or not self.value.is_finite():
            raise ValueError("REVISION_VALUE_INVALID")
        if (self.predecessor_id is None) != (self.predecessor_value is None):
            raise ValueError("REVISION_PREDECESSOR_VALUE_MISSING")
        if self.predecessor_value is not None and (
                not isinstance(self.predecessor_value, Decimal) or not self.predecessor_value.is_finite()):
            raise ValueError("REVISION_PREDECESSOR_VALUE_INVALID")
        if not all(aware(v) for v in (self.declared_release_at, self.observed_at, self.durable_verified_at)):
            raise ValueError("REVISION_AWARE_TIME_REQUIRED")
        if not self.declared_release_at <= self.observed_at <= self.durable_verified_at:
            raise ValueError("REVISION_TIME_ORDER")
        if not isinstance(self.raw_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.raw_sha256):
            raise ValueError("REVISION_SHA_INVALID")


def ordered_chain(rows: tuple[Revision, ...]) -> tuple[Revision, ...]:
    if not 0 < len(rows) <= 1000:
        raise ValueError("REVISION_EMPTY_OR_LIMIT")
    if not all(isinstance(row, Revision) for row in rows):
        raise ValueError("REVISION_TYPE_INVALID")
    if len({(r.series_id, r.period, r.unit, r.source_id) for r in rows}) != 1:
        raise ValueError("REVISION_SCOPE_CONFLICT")
    by_id = {r.revision_id: r for r in rows}
    if len(by_id) != len(rows) or len({r.raw_sha256 for r in rows}) != len(rows):
        raise ValueError("REVISION_DUPLICATE")
    roots = [r for r in rows if r.predecessor_id is None]
    if len(roots) != 1:
        raise ValueError("REVISION_ROOT_MISSING_OR_AMBIGUOUS")
    successors = {}
    for row in rows:
        if row.predecessor_id is None:
            continue
        previous = by_id.get(row.predecessor_id)
        if previous is None:
            raise ValueError("REVISION_PREDECESSOR_NOT_OBSERVED")
        if row.predecessor_id in successors:
            raise ValueError("REVISION_FORK_UNRESOLVED")
        if (row.declared_release_at <= previous.declared_release_at
                or row.predecessor_value != previous.value):
            raise ValueError("REVISION_PREDECESSOR_CONFLICT")
        successors[row.predecessor_id] = row
    chain = [roots[0]]
    seen = {roots[0].revision_id}
    while chain[-1].revision_id in successors:
        following = successors[chain[-1].revision_id]
        if following.revision_id in seen:
            raise ValueError("REVISION_CYCLE")
        chain.append(following)
        seen.add(following.revision_id)
    if len(chain) != len(rows):
        raise ValueError("REVISION_DISCONNECTED")
    return tuple(chain)


def revision_view(rows: tuple[Revision, ...], *, cutoff: datetime,
                  analysis_at: datetime, mode: str) -> dict:
    """Return a bounded explicit lineage view, not a trust/admission oracle.

    Historical release reconstruction uses only verified-at-analysis archive
    receipts and the declared-release cutoff. Durable-observation mode only
    uses receipts independently reopened by the specified cutoff. A missing
    predecessor or unresolved fork in that subset blocks the current value.
    """
    if not aware(cutoff) or not aware(analysis_at) or cutoff > analysis_at:
        raise ValueError("REVISION_CUTOFF_INVALID")
    if mode not in {"DECLARED_RELEASE_RECONSTRUCTION", "DURABLE_OBSERVED_VIEW"}:
        raise ValueError("REVISION_MODE_INVALID")
    if len(rows) > 1000 or any(not isinstance(row, Revision) for row in rows):
        raise ValueError("REVISION_TYPE_OR_LIMIT")
    if mode == "DECLARED_RELEASE_RECONSTRUCTION":
        visible = tuple(r for r in rows if r.durable_verified_at <= analysis_at
                        and r.declared_release_at <= cutoff)
    else:
        visible = tuple(r for r in rows if r.durable_verified_at <= cutoff)
    report = {"mode": mode, "cutoff": cutoff.isoformat(), "analysis_at": analysis_at.isoformat(),
              "visible_revision_count": len(visible), "selected_revision": None,
              "decision_authority": False, "execution_allowed": False, "pit_safe": False,
              "historical_capture_verified": False, "first_public_availability_verified": False,
              "complete_revision_universe_verified": False,
              "raw_receipt_authenticity_verified_by_resolver": False}
    if not visible:
        return report | {"status": "UNAVAILABLE", "reason": "NO_VISIBLE_REVISIONS"}
    try:
        chain = ordered_chain(visible)
    except ValueError as exc:
        return report | {"status": "BLOCK", "reason": str(exc)}
    last = chain[-1]
    return report | {"status": "WARN", "selected_revision": last.revision_id,
                     "value": str(last.value), "unit": last.unit,
                     "source_sha256": last.raw_sha256,
                     "declared_release_at": last.declared_release_at.isoformat(),
                     "observed_at": last.observed_at.isoformat(),
                     "durable_verified_at": last.durable_verified_at.isoformat(),
                     "ordered_revision_ids": [r.revision_id for r in chain]}
