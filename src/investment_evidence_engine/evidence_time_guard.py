"""Pure temporal guards for observed research evidence.

Effective/report period is not publication availability. These checks only
validate stated chronology, not the authenticity of a source or its receipt.
"""
from __future__ import annotations

from datetime import datetime


def aware(value: datetime | None) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def source_visible(*, available_at: datetime | None, retrieved_at: datetime | None,
                   published_at: datetime | None, cutoff: datetime,
                   admitted_at: datetime | None = None) -> bool:
    if not all(aware(value) for value in (available_at, retrieved_at, cutoff)):
        return False
    if not available_at <= retrieved_at <= cutoff:
        return False
    if published_at is not None and (not aware(published_at) or published_at > available_at):
        return False
    if admitted_at is not None and (not aware(admitted_at) or not retrieved_at <= admitted_at <= cutoff):
        return False
    return True


def decision_ref_eligible(kind: str, pit_eligible: bool) -> bool:
    return pit_eligible is True and kind in {"OBSERVATION", "COMPUTATION_OUTPUT", "EVIDENCE", "CLAIM"}


def observed_measurement_visible(*, effective_at: datetime, available_at: datetime,
                                 ingested_at: datetime, cutoff: datetime) -> bool:
    """A completed measurement must actually be observed by the cutoff.

    Not for scheduled future events or methodology changes announced in advance.
    """
    return (aware(effective_at) and source_visible(available_at=available_at,
            retrieved_at=ingested_at, published_at=None, cutoff=cutoff)
            and effective_at <= available_at)


def reference_age_seconds(*, market_at: datetime, reference_at: datetime) -> float | None:
    """A reference effective after its market quote cannot be used as contemporaneous."""
    if not aware(market_at) or not aware(reference_at) or reference_at > market_at:
        return None
    return (market_at - reference_at).total_seconds()
