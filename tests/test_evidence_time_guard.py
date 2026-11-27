from datetime import UTC, date, datetime, timedelta

import pytest

from investment_evidence_engine.evidence_time_guard import (
    decision_ref_eligible,
    event_cutoff_status,
    market_event_reference,
    observed_measurement_visible,
    reference_age_seconds,
    source_visible,
    validate_event_cutoff,
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


@pytest.mark.parametrize(("published", "retrieved", "cutoff", "expected"), [
    ("2026-11-26T14:00:00+08:00", "2026-11-26T14:01:00+08:00",
     "2026-11-26T08:30:00+08:00", "AFTER_CUTOFF"),
    ("2026-11-26T07:00:00+08:00", "2026-11-26T09:00:00+08:00",
     "2026-11-26T08:30:00+08:00", "AFTER_CUTOFF"),
    ("2026-11-26T07:00:00+08:00", None,
     "2026-11-26T08:30:00+08:00", "UNVERIFIED_TIME"),
    ("2026-11-26 07:00:00", "2026-11-26T07:30:00+08:00",
     "2026-11-26T08:30:00+08:00", "UNVERIFIED_TIME"),
    ("2026-11-26", "2026-11-26T07:30:00+08:00",
     "2026-11-26T08:30:00+08:00", "UNVERIFIED_TIME"),
    ("2026-11-26T07:00:00+08:00", "2026-11-26T06:30:00+08:00",
     "2026-11-26T08:30:00+08:00", "UNVERIFIED_TIME"),
    ("2026-11-26T07:00:00+08:00", "2026-11-26T00:30:00Z",
     "2026-11-26T08:30:00+08:00", "RECORDED_CHRONOLOGY_ONLY"),
    ("2026-11-26 16:00", None, "2026-11-26", "DAY_SCOPE_ONLY"),
    ("2026-11-26T17:00:00Z", None, "2026-11-26", "AFTER_CUTOFF"),
    ("2026-11-26", "2026-11-27", "2026-11-26", "AFTER_CUTOFF"),
    (None, None, "2026-11-26", "UNVERIFIED_TIME"),
    ("not a date", None, "2026-11-26", "UNVERIFIED_TIME"),
    (None, None, None, "UNBOUNDED_RESEARCH"),
])
def test_event_cutoff_never_rounds_intraday_time(published, retrieved, cutoff, expected):
    assert event_cutoff_status(published, retrieved, cutoff) == expected


@pytest.mark.parametrize("cutoff", ["2026-11-26 08:30", "2026-02-30", "junk", ""])
def test_invalid_or_naive_exact_cutoff_is_rejected(cutoff):
    with pytest.raises(ValueError, match="EVENT_CUTOFF_REQUIRES"):
        validate_event_cutoff(cutoff)


def test_close_boundary_and_date_only_precision():
    sessions = (date(2026, 11, 26), date(2026, 11, 27), date(2026, 11, 30))
    assert market_event_reference("2026-11-26", sessions)[:2] == (
        "2026-11-27", "DATE_ONLY_NEXT_TRADING_DAY")
    assert market_event_reference("2026-11-26T15:00:00+08:00", sessions)[:2] == (
        "2026-11-27", "AFTER_CLOSE_OR_NONTRADING_NEXT_TRADING_DAY")
    assert market_event_reference("2026-11-27T15:01:00+08:00", sessions)[0] == "2026-11-30"
    assert market_event_reference("2026-11-28T09:00:00+08:00", sessions)[0] == "2026-11-30"
    assert market_event_reference("2026-11-30T15:00:00+08:00", sessions)[0] is None
    result = market_event_reference("2026-11-26 14:00", sessions)
    assert result[1] == "PRE_CLOSE_SAME_TRADING_DAY"
    assert "SOURCE_TIMEZONE_UNVERIFIED_LOCAL_REFERENCE_ONLY" in result[2]
    assert market_event_reference("2026-11-26", ())[0] is None
    with pytest.raises(ValueError, match="CALENDAR_NOT_ORDERED"):
        market_event_reference("2026-11-26", sessions[::-1])


@pytest.mark.parametrize(("release", "day", "local_hour"), [
    # Official FOMC statement, Sep 17 EDT vs Dec 10 EST.
    # https://www.federalreserve.gov/newsevents/pressreleases/monetary20250917a.htm
    # https://www.federalreserve.gov/newsevents/pressreleases/monetary20251210a.htm
    ("2025-09-17T14:00:00-04:00", date(2025, 9, 18), 2),
    ("2025-12-10T14:00:00-05:00", date(2025, 12, 11), 3),
])
def test_public_fomc_release_clock_examples_not_historical_receipts(release, day, local_hour):
    ref, rule, _ = market_event_reference(release, (day,))
    assert datetime.fromisoformat(ref).date() == day
    assert datetime.fromisoformat(ref).hour == local_hour
    assert rule == "PRE_CLOSE_SAME_TRADING_DAY"
    before = datetime.fromisoformat(release) - timedelta(seconds=1)
    assert event_cutoff_status(release, None, before.isoformat()) == "AFTER_CUTOFF"
    # Web retrieval in 2026 cannot prove capture in 2025.
    assert event_cutoff_status(release, "2026-11-26T17:00:00+08:00",
                               datetime.combine(day, datetime.min.time(), tzinfo=UTC).isoformat()) == "AFTER_CUTOFF"


@pytest.mark.parametrize(("effective_day","issuer_reported_release","issuer_document_day","observed_at"),[
    # Real public runner observations, 45939309237 / 45939510952.
    ("2024-06-30","2024-09-30","2024-10-30","2026-11-27T04:20:23.748605+00:00"),
    ("2024-12-31","2025-04-18","2025-08-30","2026-11-27T04:22:28.551244+00:00"),
])
def test_classification_period_and_issuer_reported_release_do_not_backdate_observation(
        effective_day, issuer_reported_release, issuer_document_day, observed_at):
    retrieved=datetime.fromisoformat(observed_at)
    effective=datetime.fromisoformat(effective_day+"T15:00:00+08:00")
    for day in (effective_day,issuer_reported_release,issuer_document_day):
        cutoff=datetime.fromisoformat(day+"T23:59:59+08:00")
        assert not source_visible(available_at=None,retrieved_at=retrieved,published_at=None,cutoff=cutoff)
        # Even assigning a hypothetical earliest availability cannot remove the late retrieval.
        assert not observed_measurement_visible(effective_at=effective,available_at=effective,
                                                ingested_at=retrieved,cutoff=cutoff)
        assert event_cutoff_status(issuer_reported_release,observed_at,cutoff.isoformat())=="AFTER_CUTOFF"
    assert not source_visible(available_at=None,retrieved_at=retrieved,published_at=None,cutoff=retrieved)
    assert event_cutoff_status(issuer_reported_release,observed_at,retrieved.isoformat())=="UNVERIFIED_TIME"
