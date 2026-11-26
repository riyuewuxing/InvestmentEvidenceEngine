"""Mature-only settlement of the fixed public control pilot.

This extension must be committed before the target session. A caller must
independently pin the first freeze and first eligible outcome run receipts;
self-recomputed SHA values do not authenticate their observation history.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path

from .historical_capture import SH
from .prospective_assessment import (
    THRESHOLD,
    DailyAssessmentBatch,
    DailyAssessmentRow,
    actual_direction,
    assess_daily_cohort,
)
from .public_prediction_pilot import (
    FIELDS,
    PILOT_ID,
    SYMBOL,
    TARGET,
    _read_rows,
    canonical_bytes,
    raw_return,
    sha256,
    verify_frozen,
)

FROZEN_PUBLIC_SHA256 = "1501bc46dc9fd0fbc5212ec774bee6759666162be469ff1d663ab1995204fd0b"
FROZEN_PUBLIC_PATH = Path("pilot-receipts/public-control-20261127-frozen.json")

MATURITY = datetime.combine(TARGET, time(15, 30), SH)
DEADLINE = datetime.combine(date(2026, 11, 30), time(23, 59, 59), SH)


def settlement_policy() -> dict:
    return {
        "pilot_id": PILOT_ID,
        "target": TARGET.isoformat(),
        "earliest_capture": MATURITY.isoformat(),
        "latest_capture": DEADLINE.isoformat(),
        "first_eligible_outcome_run_only": True,
        "no_missing_result_backfill": True,
        "single_vendor": True,
        "benchmark": "FLAT",
        "research_only": True,
        "execution_allowed": False,
    }


def validate_outcome_time(started: datetime, observed: datetime) -> None:
    if any(t.utcoffset() is None for t in (started, observed)):
        raise ValueError("PILOT_OUTCOME_TIME_NAIVE")
    if not MATURITY <= started <= observed <= DEADLINE:
        raise ValueError("PILOT_OUTCOME_OUTSIDE_WINDOW")
    if (observed - started).total_seconds() > 120:
        raise ValueError("PILOT_OUTCOME_CAPTURE_EXCEEDED")


def outcome_observation(rows: list[list[str]], *, started: datetime, observed: datetime) -> dict:
    validate_outcome_time(started, observed)
    if len(rows) > 1:
        raise ValueError("PILOT_OUTCOME_DUPLICATE_ROW")
    status, value = "UNAVAILABLE", None
    if rows:
        row = rows[0]
        if len(row) != len(FIELDS) or any(not isinstance(x, str) for x in row):
            raise ValueError("PILOT_OUTCOME_SCHEMA")
        if row[0] != TARGET.isoformat() or row[1] != "sh." + SYMBOL or row[-2] != "3":
            raise ValueError("PILOT_OUTCOME_IDENTITY")
        if row[-1] == "0":
            status = "UNTRADEABLE"
        else:
            value = str(raw_return(row, TARGET.isoformat()))
            status = "OBSERVED"
    policy = settlement_policy()
    return {
        "status": status,
        "policy": policy,
        "policy_sha256": sha256(policy),
        "started_at": started.astimezone(UTC).isoformat(),
        "observed_at": observed.astimezone(UTC).isoformat(),
        "fields": list(FIELDS),
        "rows": rows,
        "raw_intraday_return": value,
    }


def verify_outcome(receipt: dict) -> None:
    reconstructed = outcome_observation(
        receipt["rows"],
        started=datetime.fromisoformat(receipt["started_at"]),
        observed=datetime.fromisoformat(receipt["observed_at"]),
    )
    if canonical_bytes(reconstructed) != canonical_bytes(receipt):
        raise ValueError("PILOT_OUTCOME_RECEIPT_MISMATCH")


def assess(frozen: dict, outcome: dict, *, expected_freeze_sha256: str,
           expected_outcome_sha256: str, now: datetime) -> dict:
    verify_frozen(frozen)
    verify_outcome(outcome)
    if sha256(frozen) != expected_freeze_sha256 or sha256(outcome) != expected_outcome_sha256:
        raise ValueError("PILOT_EXTERNAL_RECEIPT_HASH_MISMATCH")
    if now.utcoffset() is None or now < datetime.fromisoformat(outcome["observed_at"]):
        raise ValueError("PILOT_ASSESSMENT_BEFORE_OBSERVATION")
    value = outcome["raw_intraday_return"]
    number = float(value) if value is not None else None
    if value is not None:
        exact = Decimal(value)
        direction = "UP" if exact > THRESHOLD else "DOWN" if exact < -THRESHOLD else "FLAT"
        if actual_direction(number) != direction:
            raise ValueError("PILOT_OUTCOME_LABEL_PRECISION_MISMATCH")
    result = assess_daily_cohort(
        TARGET, TARGET, (SYMBOL,),
        (DailyAssessmentBatch(session=TARGET, rows=(DailyAssessmentRow(
            subject_id=SYMBOL, disposition="SELECTED", direction=frozen["direction"],
            outcome_status=outcome["status"],
            observed_return=number,
        ),)),), now=now,
    )
    return {
        "pilot_id": PILOT_ID,
        "freeze_sha256": expected_freeze_sha256,
        "outcome_sha256": expected_outcome_sha256,
        "first_run_provenance_verification_by_caller_required": True,
        "assessment": result,
        "model_promotion_allowed": False,
    }


def collect() -> dict:
    import contextlib
    import io

    import baostock as bs

    started = datetime.now(UTC)
    validate_outcome_time(started, started)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        login = bs.login()
        if login.error_code != "0":
            raise ValueError("PILOT_OUTCOME_VENDOR_LOGIN")
        try:
            rows = _read_rows(bs.query_history_k_data_plus(
                "sh." + SYMBOL, ",".join(FIELDS), start_date=TARGET.isoformat(),
                end_date=TARGET.isoformat(), frequency="d", adjustflag="3"), FIELDS, 1)
        finally:
            bs.logout()
    result = outcome_observation(rows, started=started, observed=datetime.now(UTC))
    verify_outcome(result)
    return result


def load_pinned_freeze(path: Path = FROZEN_PUBLIC_PATH) -> dict:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FROZEN_PUBLIC_SHA256:
        raise ValueError("PILOT_PINNED_FREEZE_BYTES_MISMATCH")
    receipt = json.loads(raw)
    verify_frozen(receipt)
    return receipt


def main() -> int:
    try:
        frozen = load_pinned_freeze()
        receipt = collect()
        assessment = assess(frozen, receipt, expected_freeze_sha256=FROZEN_PUBLIC_SHA256,
                            expected_outcome_sha256=sha256(receipt), now=datetime.now(UTC))
    except Exception as exc:
        print("PUBLIC_PILOT_OUTCOME_BLOCKED " + type(exc).__name__)
        return 2
    print("PUBLIC_PILOT_OUTCOME_RECEIPT " + canonical_bytes(receipt).decode("utf-8"))
    print("PUBLIC_PILOT_OUTCOME_SHA256 " + sha256(receipt))
    print("PUBLIC_PILOT_ASSESSMENT " + canonical_bytes(assessment).decode("utf-8"))
    print("PUBLIC_PILOT_ASSESSMENT_SHA256 " + sha256(assessment))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
