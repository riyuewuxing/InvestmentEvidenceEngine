"""One fixed, preregistered public control pilot, not a trading strategy.

The immutable Git commit precedes acquisition; only the first run is eligible.
Normalized vendor observations, not original network-body or fill evidence.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from .historical_capture import SH
from .market_calendar import SCHEDULE_VERSION, scheduled_days
from .prospective_assessment import THRESHOLD

PILOT_ID = "public_daily_control_20261127_v1"
SYMBOL = "600519"
PLANNING_DAY = date(2026, 11, 26)
TARGET = date(2026, 11, 27)
LAST_INPUT = date(2026, 11, 25)
FIRST = LAST_INPUT - timedelta(days=20)
FIELDS = ("date", "code", "open", "close", "volume", "adjustflag", "tradestatus")


def canonical_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256(value: dict) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def preregistration() -> dict:
    return {
        "pilot_id": PILOT_ID,
        "strategy": "daily_intraday_persistence_5",
        "strategy_version": "1.0",
        "fixed_symbols": [SYMBOL],
        "first_target": TARGET.isoformat(),
        "last_target": TARGET.isoformat(),
        "planning_day": PLANNING_DAY.isoformat(),
        "input_end": LAST_INPUT.isoformat(),
        "input_count": 5,
        "threshold": str(THRESHOLD),
        "label": "RAW_OPEN_TO_CLOSE_GROSS_NOT_EXECUTABLE_TRADE",
        "benchmark": "FLAT",
        "calendar_version": SCHEDULE_VERSION,
        "source": "baostock_unadjusted_daily",
        "first_run_only": True,
        "research_only": True,
        "execution_allowed": False,
    }


def validate_freeze_time(started: datetime, observed: datetime) -> None:
    if started.utcoffset() is None or observed.utcoffset() is None or started > observed:
        raise ValueError("PILOT_OBSERVATION_TIME_INVALID")
    if any(t.astimezone(SH).date() != PLANNING_DAY for t in (started, observed)):
        raise ValueError("PILOT_FREEZE_WINDOW_CLOSED")
    if (observed - started).total_seconds() > 120:
        raise ValueError("PILOT_CAPTURE_WINDOW_EXCEEDED")


def calendar_rows_expected() -> list[list[str]]:
    return [[row.day.isoformat(), "1" if row.is_trading_day else "0"]
            for row in scheduled_days(FIRST, TARGET)]


def input_sessions() -> list[str]:
    rows = calendar_rows_expected()
    return [d for d, is_open in rows if d <= LAST_INPUT.isoformat() and is_open == "1"][-5:]


def _direction(value: Decimal) -> str:
    return "UP" if value > THRESHOLD else "DOWN" if value < -THRESHOLD else "FLAT"


def raw_return(row: list[str], expected_session: str) -> Decimal:
    if len(row) != len(FIELDS) or any(not isinstance(x, str) for x in row):
        raise ValueError("PILOT_ROW_SCHEMA")
    day, code, op, close, volume, adjustment, trading = row
    if day != expected_session or code != "sh." + SYMBOL or adjustment != "3":
        raise ValueError("PILOT_ROW_IDENTITY")
    if trading != "1":
        raise ValueError("PILOT_ROW_NOT_TRADING")
    prices = (Decimal(op), Decimal(close), Decimal(volume))
    if any(not x.is_finite() or x <= 0 for x in prices):
        raise ValueError("PILOT_ROW_NOT_POSITIVE")
    return prices[1] / prices[0] - 1


def freeze(calendar: list[list[str]], rows: list[list[str]], *,
           started: datetime, observed: datetime) -> dict:
    validate_freeze_time(started, observed)
    if calendar != calendar_rows_expected():
        raise ValueError("PILOT_CALENDAR_MISMATCH")
    next_sessions = [d for d, flag in calendar if d > PLANNING_DAY.isoformat() and flag == "1"]
    if next_sessions != [TARGET.isoformat()]:
        raise ValueError("PILOT_TARGET_MISMATCH")
    sessions = input_sessions()
    if len(rows) != 5:
        raise ValueError("PILOT_INPUT_COUNT")
    mean = sum((raw_return(row, session) for row, session in zip(rows, sessions, strict=True)),
               Decimal(0)) / 5
    observation = {
        "started_at": started.astimezone(UTC).isoformat(),
        "observed_at": observed.astimezone(UTC).isoformat(),
        "calendar_rows": calendar,
        "daily_fields": list(FIELDS),
        "daily_rows": rows,
    }
    reg = preregistration()
    return {
        "status": "FROZEN_PENDING",
        "registration": reg,
        "registration_sha256": sha256(reg),
        "observation": observation,
        "observation_sha256": sha256(observation),
        "direction": _direction(mean),
        "mean_raw_intraday_return": str(mean),
        "single_vendor": True,
        "raw_vendor_body_archived": False,
        "probability_calibrated": False,
        "outcome": None,
        "research_only": True,
        "execution_allowed": False,
    }


def verify_frozen(receipt: dict) -> None:
    observation = receipt["observation"]
    reconstructed = freeze(
        observation["calendar_rows"], observation["daily_rows"],
        started=datetime.fromisoformat(observation["started_at"]),
        observed=datetime.fromisoformat(observation["observed_at"]),
    )
    if canonical_bytes(reconstructed) != canonical_bytes(receipt):
        raise ValueError("PILOT_RECEIPT_MISMATCH")


def _read_rows(result, fields: tuple[str, ...], limit: int) -> list[list[str]]:
    if result.error_code != "0" or tuple(result.fields) != fields:
        raise ValueError("PILOT_VENDOR_SCHEMA_OR_QUERY")
    rows = []
    while result.next():
        if len(rows) >= limit:
            raise ValueError("PILOT_VENDOR_ROW_LIMIT")
        rows.append(result.get_row_data())
    if result.error_code != "0":
        raise ValueError("PILOT_VENDOR_QUERY")
    return rows


def collect() -> dict:
    import contextlib
    import io

    import baostock as bs

    started = datetime.now(UTC)
    validate_freeze_time(started, started)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        login = bs.login()
        if login.error_code != "0":
            raise ValueError("PILOT_VENDOR_LOGIN")
        try:
            calendar = _read_rows(
                bs.query_trade_dates(start_date=FIRST.isoformat(), end_date=TARGET.isoformat()),
                ("calendar_date", "is_trading_day"), 30,
            )
            rows = _read_rows(bs.query_history_k_data_plus(
                "sh." + SYMBOL, ",".join(FIELDS), start_date=input_sessions()[0],
                end_date=LAST_INPUT.isoformat(), frequency="d", adjustflag="3"), FIELDS, 5)
        finally:
            bs.logout()
    receipt = freeze(calendar, rows, started=started, observed=datetime.now(UTC))
    verify_frozen(receipt)
    return receipt


def main() -> int:
    try:
        receipt = collect()
    except Exception as exc:
        # Never retry a failed first pilot run or silently choose another symbol.
        print("PUBLIC_PILOT_BLOCKED " + type(exc).__name__)
        return 2
    print("PUBLIC_PILOT_RECEIPT " + canonical_bytes(receipt).decode("utf-8"))
    print("PUBLIC_PILOT_SHA256 " + sha256(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
