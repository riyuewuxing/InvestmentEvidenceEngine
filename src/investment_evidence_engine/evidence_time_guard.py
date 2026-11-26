"""Pure temporal guards for observed research evidence.

Effective/report period is not publication availability. These checks only
validate stated chronology, not the authenticity of a source or its receipt.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo


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


SHANGHAI = ZoneInfo("Asia/Shanghai")


def parse_event_stamp(value: str | None) -> tuple[datetime | None, bool]:
    """Preserve date-only precision; do not silently attach a time zone."""
    if not isinstance(value, str):
        return None, False
    value = value.strip()
    day_only = bool(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value))
    try:
        if day_only:
            return datetime.combine(date.fromisoformat(value), time.min), True
        if not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}", value):
            return None, False
        return datetime.fromisoformat(value), False
    except (ValueError, OverflowError):
        return None, False


def _market_day(value: datetime) -> date:
    return (value.astimezone(SHANGHAI) if aware(value) else value).date()


def validate_event_cutoff(as_of: str | None) -> tuple[datetime | None, bool]:
    if as_of is None:
        return None, False
    cutoff, day_only = parse_event_stamp(as_of)
    if cutoff is None or (not day_only and not aware(cutoff)):
        raise ValueError("EVENT_CUTOFF_REQUIRES_ISO_DATE_OR_AWARE_INSTANT")
    return cutoff, day_only


def event_cutoff_status(published_at: str | None, retrieved_at: str | None,
                        as_of: str | None) -> str:
    """Screen event rows by a declared research scope, never grant PIT admission.

    Date scope is a retrospective local-day filter, not an intraday cutoff.
    A precise cutoff requires explicit offsets and actual stated retrieval time.
    Publication is not proof of availability, original bytes, or capture vintage.
    """
    cutoff, day_scope = validate_event_cutoff(as_of)
    if cutoff is None:
        return "UNBOUNDED_RESEARCH"
    published, published_day_only = parse_event_stamp(published_at)
    retrieved, retrieved_day_only = parse_event_stamp(retrieved_at)
    for stamp in (published, retrieved):
        if stamp is None:
            continue
        if _market_day(stamp) > _market_day(cutoff):
            return "AFTER_CUTOFF"
        if not day_scope and aware(stamp) and stamp > cutoff:
            return "AFTER_CUTOFF"
    if published is None or (retrieved_at is not None and retrieved is None):
        return "UNVERIFIED_TIME"
    if retrieved is not None:
        if _market_day(retrieved) < _market_day(published):
            return "UNVERIFIED_TIME"
        if aware(published) and aware(retrieved) and retrieved < published:
            return "UNVERIFIED_TIME"
    if day_scope:
        return "DAY_SCOPE_ONLY"
    if (published_day_only or retrieved_day_only or
            not aware(published) or not aware(retrieved)):
        return "UNVERIFIED_TIME"
    return "RECORDED_CHRONOLOGY_ONLY"


def market_event_reference(published_at: str | None, sessions: tuple[date, ...]
                           ) -> tuple[str | None, str, list[str]]:
    """Close-based mainland-market reference, not an execution timestamp."""
    published, day_only = parse_event_stamp(published_at)
    if published is None:
        return None, "UNKNOWN_PUBLISHED_AT", ["PUBLISHED_AT_MISSING_OR_UNPARSEABLE"]
    if not sessions or any(type(day) is not date for day in sessions):
        return None, "TRADING_CALENDAR_REQUIRED", ["TRADING_CALENDAR_UNAVAILABLE"]
    if sessions != tuple(sorted(set(sessions))):
        raise ValueError("EVENT_CALENDAR_NOT_ORDERED_UNIQUE")
    local = published.astimezone(SHANGHAI) if aware(published) else published
    day = local.date()
    warnings = ["MARKET_REFERENCE_NOT_EXECUTABLE"]
    if not day_only and not aware(published):
        warnings.append("SOURCE_TIMEZONE_UNVERIFIED_LOCAL_REFERENCE_ONLY")
    if not day_only and day in sessions and local.time() < time(15, 0):
        return local.isoformat(), "PRE_CLOSE_SAME_TRADING_DAY", warnings
    later = next((session for session in sessions if session > day), None)
    rule = ("DATE_ONLY_NEXT_TRADING_DAY" if day_only
            else "AFTER_CLOSE_OR_NONTRADING_NEXT_TRADING_DAY")
    if later is None:
        warnings.append("NO_NEXT_TRADING_DAY_IN_CALENDAR")
    return later.isoformat() if later is not None else None, rule, warnings
