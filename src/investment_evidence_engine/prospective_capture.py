"""Bounded real vendor collection for a preregistered public daily cohort.

No account data, API credentials, scheduled side effects, fills or probabilities.
Caller pins the first run, source receipts and complete event history externally.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from .historical_capture import SH
from .market_calendar import scheduled_days
from .prospective_assessment import (
    THRESHOLD,
    DailyAssessmentBatch,
    DailyAssessmentRow,
    actual_direction,
)
from .prospective_protocol import (
    CohortBatchRecord,
    CohortProtocol,
    deadline,
    maturity,
    planning_start,
    protocol_sha256,
)

FIELDS = ("date", "code", "open", "close", "volume", "adjustflag", "tradestatus")


def canonical_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def receipt_sha256(value: dict) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def vendor_symbol(symbol: str) -> str:
    return ("sh." if symbol.startswith(("60", "68")) else "sz.") + symbol


def verify_window(protocol: CohortProtocol, target: date, phase: str,
                  started: datetime, observed: datetime) -> None:
    if target not in protocol.sessions():
        raise ValueError("COHORT_TARGET_NOT_REGISTERED")
    if any(t.utcoffset() is None for t in (started, observed)) or started > observed:
        raise ValueError("COHORT_CAPTURE_CLOCK")
    if (observed-started).total_seconds() > 120:
        raise ValueError("COHORT_CAPTURE_WATCHDOG_WINDOW")
    if phase == "freeze":
        if not planning_start(target) <= started <= observed < planning_start(target)+timedelta(days=1):
            raise ValueError("COHORT_FREEZE_WINDOW")
    elif phase == "settle":
        if not maturity(target) <= started <= observed <= deadline(target):
            raise ValueError("COHORT_SETTLE_WINDOW")
    else:
        raise ValueError("COHORT_UNKNOWN_PHASE")


def calendar_expected(target: date) -> list[list[str]]:
    return [[r.day.isoformat(), "1" if r.is_trading_day else "0"]
            for r in scheduled_days(target-timedelta(days=22), target)]


def expected_inputs(target: date) -> list[str]:
    end = target-timedelta(days=2)
    return [d for d, flag in calendar_expected(target) if d <= end.isoformat() and flag == "1"][-5:]


def _validate_row(symbol: str, day: str, row: list[str]) -> Decimal | None:
    if len(row) != len(FIELDS) or any(not isinstance(x, str) for x in row):
        raise ValueError("ROW_SCHEMA")
    session, code, op, cl, volume, adj, trading = row
    if session != day or code != vendor_symbol(symbol) or adj != "3":
        raise ValueError("ROW_IDENTITY")
    if trading == "0":
        return None
    if trading != "1":
        raise ValueError("ROW_TRADING_STATUS")
    try:
        prices = (Decimal(op), Decimal(cl), Decimal(volume))
    except InvalidOperation as exc:
        raise ValueError("ROW_NUMERIC_FORMAT") from exc
    if any(not x.is_finite() or x <= 0 for x in prices):
        raise ValueError("ROW_NONPOSITIVE")
    return prices[1]/prices[0]-1


def _direction(value: Decimal) -> str:
    return "UP" if value > THRESHOLD else "DOWN" if value < -THRESHOLD else "FLAT"


def _safe_error(entry: dict) -> str | None:
    if set(entry) == {"error"} and isinstance(entry["error"], str):
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", entry["error"]):
            return entry["error"]
    return None


def _normalize_entry(symbol: str, target: date, phase: str, entry: dict) -> tuple[dict, dict]:
    error = _safe_error(entry)
    if error is None:
        try:
            if set(entry) != {"rows"} or not isinstance(entry["rows"], list):
                raise ValueError("ENTRY_SCHEMA")
            rows = entry["rows"]
            if phase == "freeze":
                expected = expected_inputs(target)
                if len(rows) != len(expected) or len(expected) != 5:
                    raise ValueError("INPUT_COUNT")
                returns = [_validate_row(symbol, day, row)
                           for day, row in zip(expected, rows, strict=True)]
                if any(v is None for v in returns):
                    raise ValueError("INPUT_NOT_TRADING")
                mean = sum(returns, Decimal(0))/5
                return {"rows": rows}, {"subject_id": symbol, "disposition": "SELECTED",
                    "direction": _direction(mean), "mean_raw_intraday_return": str(mean)}
            if len(rows) > 1:
                raise ValueError("OUTCOME_DUPLICATE")
            if not rows:
                return {"rows": []}, {"subject_id": symbol, "outcome_status": "UNAVAILABLE",
                                      "raw_intraday_return": None}
            ret = _validate_row(symbol, target.isoformat(), rows[0])
            return {"rows": rows}, {"subject_id": symbol,
                "outcome_status": "UNTRADEABLE" if ret is None else "OBSERVED",
                "raw_intraday_return": None if ret is None else str(ret)}
        except (ValueError, TypeError, InvalidOperation) as exc:
            error = "INVALID_" + type(exc).__name__.upper()
    normalized = {"error": error}
    if phase == "freeze":
        return normalized, {"subject_id": symbol, "disposition": "UNAVAILABLE", "direction": None,
                            "mean_raw_intraday_return": None}
    return normalized, {"subject_id": symbol, "outcome_status": "UNAVAILABLE",
                        "raw_intraday_return": None}


def build_receipt(protocol: CohortProtocol, target: date, phase: str, observations: dict, *,
                  started: datetime, observed: datetime, calendar: list | None = None) -> dict:
    verify_window(protocol, target, phase, started, observed)
    if set(observations) != set(protocol.symbols):
        raise ValueError("COHORT_MEMBER_OMITTED")
    if phase == "freeze":
        if calendar != calendar_expected(target):
            raise ValueError("COHORT_VENDOR_CALENDAR_MISMATCH")
    elif calendar is not None:
        raise ValueError("COHORT_SETTLEMENT_CALENDAR_UNEXPECTED")
    normalized, rows = {}, []
    for symbol in protocol.symbols:
        normalized[symbol], row = _normalize_entry(symbol, target, phase, observations[symbol])
        rows.append(row)
    return {
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256(protocol),
        "target": target.isoformat(),
        "phase": phase,
        "status": "FROZEN_PENDING" if phase == "freeze" else "OUTCOME_OBSERVED_OR_UNAVAILABLE",
        "input_end": (target-timedelta(days=2)).isoformat() if phase == "freeze" else None,
        "started_at": started.astimezone(UTC).isoformat(),
        "observed_at": observed.astimezone(UTC).isoformat(),
        "calendar_rows": calendar,
        "daily_fields": list(FIELDS),
        "observations": normalized,
        "rows": rows,
        "single_vendor": True,
        "raw_vendor_body_archived": False,
        "research_only": True,
        "execution_allowed": False,
    }


def verify_receipt(protocol: CohortProtocol, receipt: dict, *, expected_sha256: str) -> None:
    rederived = build_receipt(protocol, date.fromisoformat(receipt["target"]), receipt["phase"],
        receipt["observations"], started=datetime.fromisoformat(receipt["started_at"]),
        observed=datetime.fromisoformat(receipt["observed_at"]), calendar=receipt["calendar_rows"])
    if (canonical_bytes(rederived) != canonical_bytes(receipt)
            or receipt_sha256(receipt) != expected_sha256):
        raise ValueError("COHORT_RECEIPT_MISMATCH")


def to_batch_record(protocol: CohortProtocol, frozen: dict, *, frozen_sha256: str,
                    outcome: dict | None = None, outcome_sha256: str | None = None) -> CohortBatchRecord:
    verify_receipt(protocol, frozen, expected_sha256=frozen_sha256)
    if frozen["phase"] != "freeze":
        raise ValueError("COHORT_EXPECTED_FREEZE")
    if (outcome is None) != (outcome_sha256 is None):
        raise ValueError("COHORT_OUTCOME_HASH_MISSING")
    if outcome is not None:
        verify_receipt(protocol, outcome, expected_sha256=outcome_sha256)
        if outcome["phase"] != "settle" or outcome["target"] != frozen["target"]:
            raise ValueError("COHORT_OUTCOME_WRONG_SESSION")
    rows = []
    for i, predicted in enumerate(frozen["rows"]):
        observed = outcome["rows"][i] if outcome is not None else None
        value = observed["raw_intraday_return"] if observed else None
        number = float(value) if value is not None else None
        if value is not None and actual_direction(number) != _direction(Decimal(value)):
            raise ValueError("COHORT_LABEL_PRECISION_MISMATCH")
        rows.append(DailyAssessmentRow(subject_id=predicted["subject_id"],
            disposition=predicted["disposition"], direction=predicted["direction"],
            outcome_status=observed["outcome_status"] if observed else "PENDING",
            observed_return=number))
    return CohortBatchRecord(protocol_sha256=protocol_sha256(protocol),
        frozen_at=datetime.fromisoformat(frozen["observed_at"]),
        input_end=date.fromisoformat(frozen["input_end"]), freeze_receipt_sha256=frozen_sha256,
        outcome_observed_at=datetime.fromisoformat(outcome["observed_at"]) if outcome else None,
        outcome_receipt_sha256=outcome_sha256,
        batch=DailyAssessmentBatch(session=date.fromisoformat(frozen["target"]), rows=tuple(rows)))


def _read_rows(result, fields: tuple[str, ...], limit: int) -> list[list[str]]:
    if result.error_code != "0" or tuple(result.fields) != fields:
        raise ValueError("VENDOR_SCHEMA_OR_QUERY")
    rows = []
    while result.next():
        if len(rows) >= limit:
            raise ValueError("VENDOR_ROW_LIMIT")
        rows.append(result.get_row_data())
    if result.error_code != "0":
        raise ValueError("VENDOR_QUERY")
    return rows


def collect(protocol: CohortProtocol, target: date, phase: str) -> dict:
    """One provider session; caller must enforce a process-level timeout."""
    import baostock as bs

    started = datetime.now(UTC)
    verify_window(protocol, target, phase, started, started)
    cal, observations = None, {}
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        login = bs.login()
        if login.error_code != "0":
            raise ValueError("COHORT_VENDOR_LOGIN")
        try:
            if phase == "freeze":
                cal = _read_rows(bs.query_trade_dates(start_date=(target-timedelta(days=22)).isoformat(),
                    end_date=target.isoformat()), ("calendar_date", "is_trading_day"), 23)
                if cal != calendar_expected(target):
                    raise ValueError("COHORT_VENDOR_CALENDAR_MISMATCH")
                first, last = expected_inputs(target)[0], expected_inputs(target)[-1]
            else:
                first = last = target.isoformat()
            for symbol in protocol.symbols:
                try:
                    observations[symbol] = {"rows": _read_rows(bs.query_history_k_data_plus(
                        vendor_symbol(symbol), ",".join(FIELDS), start_date=first, end_date=last,
                        frequency="d", adjustflag="3"), FIELDS, 5 if phase == "freeze" else 1)}
                except Exception as exc:
                    observations[symbol] = {"error": type(exc).__name__}
        finally:
            bs.logout()
    receipt = build_receipt(protocol, target, phase, observations, started=started,
                            observed=datetime.now(UTC), calendar=cal)
    verify_receipt(protocol, receipt, expected_sha256=receipt_sha256(receipt))
    return receipt
