from datetime import UTC, datetime, timedelta

import pytest

from investment_evidence_engine.evidence_time_guard import (
    decision_ref_eligible,
    observed_measurement_visible,
    reference_age_seconds,
    source_visible,
)

CUT = datetime(2026, 11, 26, 7, tzinfo=UTC)
BEFORE = CUT - timedelta(hours=1)
EARLIER = BEFORE - timedelta(hours=1)


def visible(**changes):
    args = {"available_at": EARLIER, "retrieved_at": BEFORE, "published_at": EARLIER,
            "cutoff": CUT, "admitted_at": CUT}
    return source_visible(**(args | changes))


def test_order_and_aware_offsets():
    assert visible()
    assert visible(published_at=None)
    assert visible(available_at=BEFORE, retrieved_at=BEFORE)
    assert visible(available_at=EARLIER.astimezone(), retrieved_at=BEFORE)


@pytest.mark.parametrize("field", ["available_at", "retrieved_at", "published_at", "admitted_at", "cutoff"])
def test_naive_timestamps_never_inferred(field):
    assert not visible(**{field: BEFORE.replace(tzinfo=None)})


@pytest.mark.parametrize("field", ["available_at", "retrieved_at"])
def test_absence_is_not_a_historical_observation(field):
    assert not visible(**{field: None})


def test_invalid_chronology():
    assert not visible(available_at=CUT)
    assert not visible(retrieved_at=CUT + timedelta(seconds=1))
    assert not visible(published_at=BEFORE)
    assert not visible(admitted_at=EARLIER)
    assert not visible(admitted_at=CUT + timedelta(seconds=1))


def test_reference_classes():
    assert decision_ref_eligible("CLAIM", True)
    assert decision_ref_eligible("COMPUTATION_OUTPUT", True)
    assert not decision_ref_eligible("CLAIM", False)
    assert not decision_ref_eligible("SOURCE", True)
    assert not decision_ref_eligible("OUTCOME", True)


def test_completed_measurement_requires_observation_by_cutoff():
    args = dict(effective_at=EARLIER, available_at=BEFORE, ingested_at=CUT, cutoff=CUT)
    assert observed_measurement_visible(**args)
    assert not observed_measurement_visible(**(args | {"ingested_at": CUT + timedelta(seconds=1)}))
    assert not observed_measurement_visible(**(args | {"effective_at": CUT}))
    assert not observed_measurement_visible(**(args | {"effective_at": EARLIER.replace(tzinfo=None)}))
    assert not observed_measurement_visible(**(args | {"cutoff": CUT.replace(tzinfo=None)}))


def test_reference_age_is_directional_and_aware():
    assert reference_age_seconds(market_at=CUT, reference_at=BEFORE) == 3600
    assert reference_age_seconds(market_at=CUT, reference_at=CUT) == 0
    assert reference_age_seconds(market_at=BEFORE, reference_at=CUT) is None
    assert reference_age_seconds(market_at=CUT, reference_at=BEFORE.replace(tzinfo=None)) is None
