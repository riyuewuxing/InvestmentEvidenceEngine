from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from investment_evidence_engine.index_constituent_cohort import select_constituent_cohort


def t(day):
    return datetime(2026, 6, day, tzinfo=UTC)


@dataclass(frozen=True)
class Row:
    index_id: str
    effective_time: datetime
    available_at: datetime
    ingested_at: datetime
    security_id: str
    weight: float
    source_ref: str


def row(symbol, weight, vintage=1, source=None):
    return Row("synthetic", t(10), t(vintage), t(vintage), symbol, weight, source or f"dataset:{vintage}")


def select(rows, cutoff=t(15), effective=t(10)):
    return select_constituent_cohort(rows, index_id="synthetic", effective_at=effective, cutoff=cutoff)


def test_complete_new_cohort_removes_old_names_instead_of_stitching():
    old = [row("A", .6), row("B", .4)]
    new = [row("A", .3, 2), row("C", .7, 2)]
    assert [r.security_id for r in select(old + new, cutoff=t(1)).rows] == ["A", "B"]
    observed = select(old + new)
    assert [r.security_id for r in observed.rows] == ["A", "C"]
    assert observed.status == "POINT_COHORT_ONLY"
    assert observed.weight_sum == Decimal("1.0")


def test_partial_new_cohort_never_fills_from_old_or_falls_back():
    old = [row("A", .6), row("B", .4)]
    partial = row("A", .6, 2)
    result = select(old + [partial])
    assert result.rows == ()
    assert result.status == "COHORT_WEIGHT_TOTAL_UNRECONCILED"
    assert result.weight_sum == Decimal(".6")


def test_partial_new_effective_day_never_falls_back():
    new = replace(row("C", .8, 2), effective_time=t(11))
    assert select([row("A", 1), new], effective=t(11)).status == "COHORT_WEIGHT_TOTAL_UNRECONCILED"
    assert select([row("A", 1), new], effective=t(10)).rows == (row("A", 1),)


def test_no_future_ingestion_and_allow_preannouncement():
    late = replace(row("C", 1, 2), ingested_at=t(12))
    assert select([late], cutoff=t(11)).status == "NO_VISIBLE_COHORT"
    assert select([late], cutoff=t(12)).rows == (late,)
    assert select([row("A", 1)], cutoff=t(1)).status == "POINT_COHORT_ONLY"
    assert select([row("A", 1)], effective=t(9)).status == "NO_VISIBLE_COHORT"


def test_same_time_multiple_source_refs_and_duplicate_members_block():
    mixed = [row("A", .5, 2, "source:a"), row("B", .5, 2, "source:b")]
    assert select(mixed).status == "AMBIGUOUS_COHORT_SOURCE"
    assert select([row("A", .5), row("A", .5)]).status == "AMBIGUOUS_COHORT_MEMBER"


def test_split_ingestion_never_blends_rows():
    rows = [row("A", .5), replace(row("B", .5), ingested_at=t(2))]
    assert select(rows).status == "COHORT_WEIGHT_TOTAL_UNRECONCILED"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -.1, 1.1, True])
def test_invalid_weight_blocks(bad):
    assert select([row("A", bad)]).status == "INVALID_COHORT_WEIGHT"


def test_invalid_clocks_and_no_matching_index():
    invalid = replace(row("A", 1), ingested_at=t(1).replace(tzinfo=None))
    assert select([invalid]).status == "INVALID_COHORT_CLOCK"
    assert select([replace(row("A", 1), ingested_at=t(1), available_at=t(2))]).status == "INVALID_COHORT_CLOCK"
    assert select([row("A", 1)], cutoff=t(1).replace(tzinfo=None)).status == "INVALID_COHORT_CLOCK"
    assert select([replace(row("A", 1), index_id="other")]).status == "NO_VISIBLE_COHORT"


def test_rounded_weight_total_only_diagnostic_not_complete_history():
    result = select([row("A", .5), row("B", .499)])
    assert result.status == "POINT_COHORT_ONLY"
    assert result.weight_sum == Decimal(".999")
