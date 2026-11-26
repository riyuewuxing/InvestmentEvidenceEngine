"""Bounded mainland cash-market calendar observations.

The reviewed annual SSE/SZSE holiday schedules are a versioned reference,
not an automatic calendar for unsupported years or a proof of zero emergency
closures. Exact BaoStock calendar rows must match the entire date interval.
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .historical_capture import SH, validate_window

SCHEDULE_VERSION = "SSE_SZSE_2025_2026_ANNUAL_NOTICES_V1"
SCHEDULES = {
    2025: (
        ("2025-01-01", "2025-01-01"), ("2025-01-28", "2025-02-04"),
        ("2025-04-04", "2025-04-06"), ("2025-05-01", "2025-05-05"),
        ("2025-05-31", "2025-06-02"), ("2025-10-01", "2025-10-08"),
    ),
    2026: (
        ("2026-01-01", "2026-01-03"), ("2026-02-15", "2026-02-23"),
        ("2026-04-04", "2026-04-06"), ("2026-05-01", "2026-05-05"),
        ("2026-06-19", "2026-06-21"), ("2026-09-25", "2026-09-27"),
        ("2026-10-01", "2026-10-07"),
    ),
}
NOTICE_URLS = {
    2025: (
        "https://www.sse.com.cn/disclosure/announcement/general/c/c_20241223_10767108.shtml",
        "https://www.szse.cn/disclosure/notice/general/t20241223_611283.html",
    ),
    2026: (
        "https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml",
        "https://www.szse.cn/disclosure/notice/general/t20251222_618087.html",
    ),
}


class CalendarDay(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    day: date
    is_trading_day: bool


class CalendarObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    source: Literal["baostock_query_trade_dates"] = "baostock_query_trade_dates"
    first_requested: date
    last_requested: date
    observed_at: AwareDatetime
    rows: tuple[CalendarDay, ...] = Field(min_length=21, max_length=1101)


def scheduled_days(first: date, last: date) -> tuple[CalendarDay, ...]:
    if type(first) is not date or type(last) is not date or not 0 <= (last-first).days <= 1100:
        raise ValueError("CALENDAR_RANGE_INVALID")
    years = range(first.year, last.year+1)
    if any(year not in SCHEDULES for year in years):
        raise ValueError("OFFICIAL_SCHEDULE_YEAR_UNSUPPORTED")
    closures = set()
    for year in years:
        for start, end in SCHEDULES[year]:
            a, b = date.fromisoformat(start), date.fromisoformat(end)
            closures.update(a+timedelta(days=i) for i in range((b-a).days+1))
    days = tuple(first+timedelta(days=i) for i in range((last-first).days+1))
    return tuple(CalendarDay(day=d, is_trading_day=d.weekday()<5 and d not in closures) for d in days)


def check_calendar(observation: CalendarObservation, *, first: date, last: date,
                   cutoff: datetime) -> tuple[date, ...]:
    obs = CalendarObservation.model_validate(observation.model_dump())
    validate_window(first, last, obs.observed_at)
    if cutoff.utcoffset() is None or obs.observed_at > cutoff:
        raise ValueError("CALENDAR_OBSERVATION_TIME_INVALID")
    if (obs.first_requested, obs.last_requested) != (first, last):
        raise ValueError("CALENDAR_SCOPE_MISMATCH")
    expected = scheduled_days(first, last)
    if tuple(x.day for x in obs.rows) != tuple(x.day for x in expected):
        raise ValueError("CALENDAR_MISSING_DUPLICATE_OR_OUT_OF_ORDER_DATE")
    if obs.rows != expected:
        raise ValueError("VENDOR_OFFICIAL_SCHEDULE_CONFLICT")
    sessions = tuple(x.day for x in obs.rows if x.is_trading_day)
    if not sessions or sessions[-1] != last:
        raise ValueError("END_NOT_COMPLETED_TRADING_SESSION")
    return sessions


def calendar_from_vendor(rows: list, first: date, last: date,
                         observed_at: datetime) -> CalendarObservation:
    # No sorting away duplicate rows, no inference from security price dates.
    parsed = []
    for row in rows:
        if not isinstance(row, list) or len(row) != 2 or row[1] not in ("0", "1"):
            raise ValueError("CALENDAR_VENDOR_SCHEMA_INVALID")
        parsed.append(CalendarDay(day=date.fromisoformat(row[0]), is_trading_day=row[1]=="1"))
    observation = CalendarObservation(first_requested=first, last_requested=last,
        observed_at=observed_at, rows=tuple(parsed))
    check_calendar(observation, first=first, last=last, cutoff=datetime.now(SH))
    return observation


def _query_calendar(first: date, last: date) -> list:
    import baostock as bs

    login = bs.login()
    if login.error_code != "0":
        raise ValueError("CALENDAR_LOGIN_FAILED")
    try:
        rs = bs.query_trade_dates(start_date=first.isoformat(), end_date=last.isoformat())
        if rs.error_code != "0" or list(rs.fields) != ["calendar_date","is_trading_day"]:
            raise ValueError("CALENDAR_QUERY_OR_SCHEMA_FAILED")
        rows = []
        while rs.next():
            if len(rows)>=1101:
                raise ValueError("CALENDAR_VENDOR_ROW_LIMIT")
            rows.append(rs.get_row_data())
        if rs.error_code != "0":
            raise ValueError("CALENDAR_QUERY_FAILED")
        return rows
    finally:
        bs.logout()


def _child(first: str, last: str) -> None:
    stage = "REQUEST"
    try:
        a,b=date.fromisoformat(first),date.fromisoformat(last)
        validate_window(a,b,datetime.now(SH))
        scheduled_days(a,b)
        stage = "PROVIDER"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rows=_query_calendar(a,b)
        stage = "CALENDAR_VALIDATION"
        observed = calendar_from_vendor(rows,a,b,datetime.now(SH))
        print(json.dumps({"status":"OBSERVED","calendar":observed.model_dump(mode="json")}))
    except Exception as exc:
        # No third-party response bodies or credentials on stdout.
        code=str(exc) if type(exc) is ValueError and str(exc).isascii() and str(exc).isupper() and str(exc).replace("_","").isalnum() else type(exc).__name__
        print(json.dumps({"status":"BLOCKED","error_code":stage+":"+code[:80]}))


def acquire_calendar(first: date,last: date) -> CalendarObservation:
    validate_window(first,last,datetime.now(SH))
    scheduled_days(first,last)
    try:
        proc=subprocess.run([sys.executable,"-m",__name__,first.isoformat(),last.isoformat()],
            capture_output=True,check=False,timeout=25)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("CALENDAR_WATCHDOG_TIMEOUT") from exc
    if proc.returncode or len(proc.stdout)>128*1024:
        raise ValueError("CALENDAR_CHILD_EXIT_OR_OUTPUT_LIMIT")
    try:
        data=json.loads(proc.stdout)
        if not isinstance(data,dict) or data.get("status")!="OBSERVED":
            code=data.get("error_code","CALENDAR_CHILD_BLOCKED") if isinstance(data,dict) else "CALENDAR_CHILD_BLOCKED"
            if not isinstance(code,str) or len(code)>120 or not code.replace(":","").replace("_","").isalnum():
                code="CALENDAR_CHILD_BLOCKED"
            raise ValueError(code)
        observation=CalendarObservation.model_validate_json(json.dumps(data["calendar"]))
        check_calendar(observation,first=first,last=last,cutoff=datetime.now(SH))
        return observation
    except (KeyError,UnicodeError,json.JSONDecodeError) as exc:
        raise ValueError("CALENDAR_CHILD_RECEIPT_INVALID") from exc


if __name__=="__main__":
    if len(sys.argv)!=3:
        raise SystemExit(2)
    _child(*sys.argv[1:])
