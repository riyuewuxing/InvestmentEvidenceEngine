from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from investment_evidence_engine.revision_chain import Revision, ordered_chain, revision_view

NOW = datetime(2026, 11, 26, 13, tzinfo=UTC)


def rows():
    first = Revision("series", "2025-08", "JOBS", "source", "a", None, Decimal(22), None,
                     NOW-timedelta(days=3), NOW-timedelta(hours=2), NOW-timedelta(hours=1), "a"*64)
    # Older publication acquired after newer publication; use explicit lineage, not arrival order.
    second = Revision("series", "2025-08", "JOBS", "source", "b", "a", Decimal(-4), Decimal(22),
                      NOW-timedelta(days=2), NOW-timedelta(hours=4), NOW-timedelta(hours=3), "b"*64)
    return first, second


def test_retrieval_order_is_not_version_order():
    a, b = rows()
    assert ordered_chain((b, a)) == (a, b)
    result = revision_view((b, a), cutoff=NOW, analysis_at=NOW, mode="DURABLE_OBSERVED_VIEW")
    assert result["selected_revision"] == "b"
    assert not result["pit_safe"]


def test_visible_missing_predecessor_blocks():
    a, b = rows()
    result = revision_view((a, b), cutoff=NOW-timedelta(hours=2), analysis_at=NOW,
                           mode="DURABLE_OBSERVED_VIEW")
    assert result["status"] == "BLOCK"
    assert result["selected_revision"] is None


@pytest.mark.parametrize("change", [
    {"predecessor_value": Decimal(23)}, {"unit": "THOUSANDS"},
    {"source_id": "other"}, {"raw_sha256": "a"*64}, {"period": "2025-09"},
])
def test_ambiguous_or_incompatible_chain_fails(change):
    a, b = rows()
    with pytest.raises(ValueError):
        ordered_chain((a, replace(b, **change)))


def test_fork_blocks():
    a, b = rows()
    c = replace(b, revision_id="c", raw_sha256="c"*64)
    assert revision_view((a, b, c), cutoff=NOW, analysis_at=NOW,
                         mode="DURABLE_OBSERVED_VIEW")["reason"] == "REVISION_FORK_UNRESOLVED"


def test_declared_release_not_observed_time():
    a, b = rows()
    cutoff = NOW-timedelta(days=2)
    one = revision_view((a, b), cutoff=cutoff, analysis_at=NOW, mode="DECLARED_RELEASE_RECONSTRUCTION")
    two = revision_view((a, b), cutoff=cutoff, analysis_at=NOW, mode="DURABLE_OBSERVED_VIEW")
    assert one["selected_revision"] == "b"
    assert two["status"] == "UNAVAILABLE"
    assert not one["historical_capture_verified"]


def test_naive_and_future_cutoffs_block():
    for cutoff in (NOW.replace(tzinfo=None), NOW+timedelta(seconds=1)):
        with pytest.raises(ValueError):
            revision_view(rows(), cutoff=cutoff, analysis_at=NOW, mode="DURABLE_OBSERVED_VIEW")
