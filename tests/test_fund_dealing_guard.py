from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from investment_evidence_engine.fund_dealing_guard import (
    combined_subscription_cap_status,
    pcf_channel_diagnostic,
)

DAY = datetime(2026, 9, 7, 0, tzinfo=UTC)
CUTOFF = DAY + timedelta(hours=2)


def pcf(**updates):
    args = dict(effective_date=DAY, effective_at=CUTOFF,
                available_at=DAY - timedelta(hours=1), ingested_at=DAY,
                cutoff=CUTOFF, creation_allowed=False, redemption_allowed=True)
    return pcf_channel_diagnostic(**(args | updates))


def test_pcf_separate_directions_no_secondary_or_acceptance_inference():
    result = pcf()
    assert result["status"] == "SAME_SESSION_REPORTED_FLAGS"
    assert result["creation_allowed_reported"] is False
    assert result["redemption_allowed_reported"] is True
    assert not result["secondary_trading_status_inferred"]
    assert not result["actual_order_acceptance_verified"]
    assert not result["decision_authority"]


@pytest.mark.parametrize("updates", [
    {"effective_date": DAY - timedelta(days=1)},
    {"effective_date": DAY + timedelta(days=1)},
    {"effective_date": None},
    {"available_at": None},
    {"ingested_at": CUTOFF + timedelta(seconds=1)},
    {"ingested_at": None},
    {"cutoff": CUTOFF.replace(tzinfo=None)},
])
def test_pcf_missing_stale_or_future_never_open(updates):
    result = pcf(**updates)
    assert result["creation_allowed_reported"] is None
    assert result["redemption_allowed_reported"] is None


def test_missing_direction_never_inferred_from_other_direction_or_strings():
    result = pcf(creation_allowed=None, redemption_allowed=True)
    assert result["status"] == "SAME_SESSION_FLAGS_INCOMPLETE"
    assert result["creation_allowed_reported"] is None
    assert pcf(creation_allowed="N")["creation_allowed_reported"] is None


def test_local_exchange_session_is_not_utc_date():
    result = pcf(effective_date=DAY - timedelta(hours=8))
    assert result["status"] == "SAME_SESSION_REPORTED_FLAGS"


@pytest.mark.parametrize(("prior", "requested", "complete", "inclusive", "expected"), [
    ("600000", "500000", True, None, "EXCEEDS_REPORTED_CAP_REJECTION_POSSIBLE"),
    ("600000", "400000", True, None, "EXACT_CAP_WORDING_AMBIGUOUS"),
    ("600000", "400000", True, False, "EXCEEDS_REPORTED_CAP_REJECTION_POSSIBLE"),
    ("600000", "400000", True, True, "WITHIN_REPORTED_CAP_NOT_ACCEPTANCE"),
    ("600000", "399999.99", True, None, "WITHIN_REPORTED_CAP_NOT_ACCEPTANCE"),
    ("0", "500000", False, None, "AGGREGATE_UNKNOWN"),
    (None, "500000", True, None, "AGGREGATE_UNKNOWN"),
    (None, "1000000.01", False, None, "EXCEEDS_REPORTED_CAP_REJECTION_POSSIBLE"),
])
def test_combined_cap_does_not_make_per_class_or_fill_assumption(prior, requested, complete, inclusive, expected):
    assert combined_subscription_cap_status(
        requested_cny=Decimal(requested), verified_prior_cny=None if prior is None else Decimal(prior),
        aggregate_complete=complete, cap_cny=Decimal("1000000"), inclusive=inclusive,
    ) == expected


@pytest.mark.parametrize("amount", [Decimal("NaN"), Decimal("Infinity"), Decimal("-1"), Decimal("0"), 1.0])
def test_reject_invalid_amount(amount):
    with pytest.raises(ValueError):
        combined_subscription_cap_status(requested_cny=amount, verified_prior_cny=None,
                                         aggregate_complete=False, cap_cny=Decimal("1000000"), inclusive=None)


def test_pcf_later_same_day_capture_is_not_visible_at_earlier_query_time():
    result = pcf(effective_at=DAY + timedelta(minutes=30),
                 ingested_at=DAY + timedelta(hours=1))
    assert result["status"] == "PCF_CAPTURE_AFTER_QUERY_TIME_REFERENCE_ONLY"
    assert result["creation_allowed_reported"] is None
    assert result["redemption_allowed_reported"] is None


def test_pcf_announced_in_advance_is_not_current_at_cutoff():
    result = pcf(effective_date=DAY + timedelta(days=1),
                 effective_at=CUTOFF + timedelta(days=1))
    assert result["status"] == "PCF_FUTURE_SESSION_REFERENCE_ONLY"
    assert result["creation_allowed_reported"] is None
    assert result["redemption_allowed_reported"] is None
    assert not result["decision_authority"]
