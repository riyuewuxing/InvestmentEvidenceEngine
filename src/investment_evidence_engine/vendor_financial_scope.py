"""Strict vendor-declared date/basis diagnostics, not historical vintage.

Tushare docs: https://tushare.pro/document/2?doc_id=33
Type 1 is the latest consolidated report, NOT proof of the original version.
Other report types must not be silently mixed into that financial basis.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import Decimal
from numbers import Real
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


def missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def vendor_day(value: object) -> date | None:
    """Exact date-only input, no coercion of malformed date/time to a day."""
    if missing(value):
        return None
    if isinstance(value, datetime) or isinstance(value, bool):
        raise ValueError("VENDOR_DATE_TYPE")
    if type(value) is date:
        return value
    if isinstance(value, str):
        try:
            if re.fullmatch(r"[0-9]{8}", value):
                return datetime.strptime(value, "%Y%m%d").date()
            if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("VENDOR_DATE_INVALID") from exc
    raise ValueError("VENDOR_DATE_INVALID")


def financial_date_scope(report: object, announced: object, actual: object) -> dict:
    period, ann, final = (vendor_day(v) for v in (report, announced, actual))
    if period is None or (ann is None and final is None):
        raise ValueError("VENDOR_REPORT_OR_NOTICE_DAY_MISSING")
    known = [v for v in (ann, final) if v is not None]
    if any(v < period for v in known):
        raise ValueError("VENDOR_NOTICE_BEFORE_REPORT_PERIOD")
    # Do not backdate to a conflicting earlier clock. This is only a
    # conservative declared-date filter; never a first-availability timestamp.
    return {"report_period": period.isoformat(), "announced_date": None if ann is None else ann.isoformat(),
            "actual_announcement_date": None if final is None else final.isoformat(),
            "declared_date_ceiling": max(known).isoformat(),
            "notice_fields_disagree": ann is not None and final is not None and ann != final,
            "historical_vintage_verified": False, "first_availability_verified": False}


def consolidated_basis(report_type: object, *, allow_unspecified: bool = False) -> str:
    if missing(report_type):
        if allow_unspecified:
            return "UNSPECIFIED_DIAGNOSTIC_ONLY"
        raise ValueError("VENDOR_REPORT_BASIS_MISSING")
    if type(report_type) is str and report_type == "1":
        return "LATEST_CONSOLIDATED_VENDOR_ROW"
    if type(report_type) is int and report_type == 1:
        return "LATEST_CONSOLIDATED_VENDOR_ROW"
    raise ValueError("VENDOR_REPORT_BASIS_UNSUPPORTED")


def select_same_notice(rows: list[dict], *, metric_fields: tuple[str, ...]) -> dict | None:
    """Withhold a conflicting latest-day cohort; update_flag is not lineage.

    Equal normalized metric projections can collapse for diagnostic purposes
    only when scope agrees. A missing field is not a zero.
    """
    if not rows or not all(isinstance(r, dict) for r in rows):
        return None
    def projection(row):
        values = []
        for name in metric_fields:
            value = row.get(name)
            if missing(value):
                values.append(None)
            elif isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value):
                values.append(Decimal(str(value)))
            else:
                raise ValueError("VENDOR_METRIC_INVALID")
        return (row.get("dataset"), row.get("ts_code"), row.get("report_period"), row.get("available_date"),
                row.get("report_basis"), tuple(values))
    try:
        first = projection(rows[0])
        if any(projection(row) != first for row in rows[1:]):
            return None
    except (TypeError, ValueError, ArithmeticError):
        return None
    return rows[0]


def announcement_clock(announced: object, rec_time: object) -> dict:
    """Vendor label projection; naive time is an explicit Shanghai assumption.

    Date-only/midnight rec_time cannot become a same-day intraday observation.
    Conflicting announcement dates are conservatively reduced to later day.
    """
    ann = vendor_day(announced)
    exact = None
    clock_basis = "DATE_ONLY"
    if not missing(rec_time):
        if not isinstance(rec_time, str):
            raise ValueError("VENDOR_EVENT_CLOCK_TYPE")
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{8}", rec_time):
            observed_day = vendor_day(rec_time)
        elif re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})?", rec_time):
            exact = datetime.fromisoformat(rec_time)
            clock_basis = "VENDOR_LOCAL_CLOCK_ASSUMED" if exact.utcoffset() is None else "VENDOR_AWARE_CLOCK"
            local = exact.replace(tzinfo=SHANGHAI) if exact.utcoffset() is None else exact.astimezone(SHANGHAI)
            observed_day = local.date()
            exact = local
            if local.hour == local.minute == local.second == local.microsecond == 0:
                exact = None
                clock_basis = "MIDNIGHT_DATE_LABEL"
        else:
            raise ValueError("VENDOR_EVENT_CLOCK_INVALID")
    else:
        observed_day = None
    if ann is None and observed_day is None:
        raise ValueError("VENDOR_EVENT_CLOCK_MISSING")
    if ann is not None and observed_day is not None and ann != observed_day:
        exact = None
        clock_basis = "CONFLICTING_DAY_LABELS"
    day = max(v for v in (ann, observed_day) if v is not None)
    return {"local_day": day.isoformat(), "local_clock": None if exact is None else exact.isoformat(),
            "precision": "DATETIME" if exact is not None else "DATE_ONLY",
            "clock_basis": clock_basis, "first_availability_verified": False,
            "historical_vintage_verified": False}
