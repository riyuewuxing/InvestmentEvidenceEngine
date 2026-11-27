"""Read-only, pinned public prediction observations for display.

The retained pilot is a normalized receipt, not a private portfolio event or
independent raw network evidence. A preregistration is not a prediction. No
network, activation, retry, backfill, or model promotion occurs here.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

from .prospective_assessment import DailyAssessmentBatch, DailyAssessmentRow, assess_daily_cohort
from .prospective_diagnostics import assess_paired_direction_delta
from .prospective_protocol import CohortProtocol, planning_start, protocol_sha256

MAX_RECEIPT_BYTES = 256 * 1024
PILOT = "public_daily_control_20261127_v1"
TARGET = date(2026, 11, 27)
SYMBOL = "600519"
FREEZE_SHA = "1501bc46dc9fd0fbc5212ec774bee6759666162be469ff1d663ab1995204fd0b"
OUTCOME_SHA = "f25ec3d05cb8784583518a1c49f2a2152202fe25c439dd46b67cbcdbe43d8415"
ASSESSMENT_SHA = "0fd783854ecdbf5243ef86f18723f66912de8158cf77e6a8643c6c82353c4718"
PROTOCOL_RAW_SHA = "05e7d8ef70c72dc7f67293fa2e8591914988421128eef43413ad3ef0cc6c1019"
PROTOCOL_SHA = "d845cf330f008695e0dd220aa09118ed62e3952dc7238ab20110c7c4e732f0f0"


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("NONFINITE_JSON")


def _parse(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_RECEIPT_BYTES:
        raise ValueError("RECEIPT_SIZE")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    if not isinstance(value, dict):
        raise ValueError("RECEIPT_SCHEMA")
    return value


def _canonical(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def _pinned(raw: bytes, digest: str) -> dict:
    value = _parse(raw)
    if _canonical(value) != digest:
        raise ValueError("RETAINED_RECEIPT_PIN_MISMATCH")
    return value


def _read(path: Path) -> bytes | None:
    """Bound read and never follow a symlink at the file itself."""
    if path.is_symlink():
        raise ValueError("RECEIPT_SYMLINK")
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError("RECEIPT_NOT_FILE")
    with path.open("rb") as handle:
        raw = handle.read(MAX_RECEIPT_BYTES + 1)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise ValueError("RECEIPT_SIZE")
    return raw


def _pilot(frozen_raw, outcome_raw, assessment_raw, *, now):
    if any(raw is None for raw in (frozen_raw, outcome_raw, assessment_raw)):
        return {"status": "UNAVAILABLE", "reason": "Missing retained pilot receipt; no outcome inferred."}
    f = _pinned(frozen_raw, FREEZE_SHA)
    o = _pinned(outcome_raw, OUTCOME_SHA)
    a = _pinned(assessment_raw, ASSESSMENT_SHA)
    observed_at = datetime.fromisoformat(o["observed_at"])
    if observed_at > now:
        raise ValueError("PILOT_NOT_YET_OBSERVED")
    row = DailyAssessmentRow(subject_id=SYMBOL, disposition="SELECTED", direction=f["direction"],
                             outcome_status=o["status"], observed_return=None)
    batch = DailyAssessmentBatch(session=TARGET, rows=(row,))
    report = assess_daily_cohort(TARGET, TARGET, (SYMBOL,), (batch,), now=now)
    if (a["pilot_id"] != PILOT or a["freeze_sha256"] != FREEZE_SHA
            or a["outcome_sha256"] != OUTCOME_SHA or a["assessment"] != report
            or o["raw_intraday_return"] is not None or o["rows"]):
        raise ValueError("PILOT_ASSESSMENT_MISMATCH")
    paired = assess_paired_direction_delta(TARGET, TARGET, (SYMBOL,), (batch,), now=now)
    return {
        "status": "RETAINED_TERMINAL", "pilot_id": PILOT, "target": TARGET.isoformat(),
        "symbol": SYMBOL, "direction": f["direction"], "outcome_status": o["status"],
        "observed_at": o["observed_at"], "selected_count": report["disposition_counts"]["SELECTED"],
        "evaluable_count": report["observed_selected_count"],
        "accuracy": report["observed_selected_accuracy"],
        "flat_accuracy": report["observed_selected_flat_accuracy"],
        "accuracy_bounds": report["selected_accuracy_bounds_from_missing_outcomes"],
        "paired_diagnostics": paired, "normalized_receipt_pins_match": True,
        "missingness_reason": "NOT_ESTABLISHED", "retry_authorized": False,
        "first_attempt_provenance_reverified_at_runtime": False,
    }


def _cohort(raw, *, now):
    if raw is None:
        return {"status": "UNAVAILABLE", "reason": "Registered protocol receipt missing."}
    _parse(raw)
    if hashlib.sha256(raw).hexdigest() != PROTOCOL_RAW_SHA:
        raise ValueError("PROTOCOL_RAW_PIN_MISMATCH")
    protocol = CohortProtocol.model_validate_json(raw)
    if protocol_sha256(protocol) != PROTOCOL_SHA or now < protocol.registered_at:
        raise ValueError("PROTOCOL_IDENTITY_OR_CLOCK")
    sessions = protocol.sessions()
    start = planning_start(sessions[0])
    before = now < start
    # This view has no live receipt index. Do not imply no attempts, zero
    # observed slots, or expiry after the registered planning window opens.
    return {
        "status": "PREREGISTERED_NOT_STARTED" if before else "REGISTERED_RECEIPTS_NOT_CHECKED",
        "protocol_id": protocol.protocol_id, "first": protocol.first.isoformat(),
        "last": protocol.last.isoformat(), "symbols": list(protocol.symbols),
        "expected_sessions": len(sessions), "expected_slots": len(sessions) * len(protocol.symbols),
        "first_planning_at": start.isoformat(), "evaluable_count": 0 if before else None,
        "receipt_index_verified": False, "protocol_pin_matches": True,
        "activation_authorized": False, "retry_authorized": False, "backfill_authorized": False,
    }


def project_prediction_observations(frozen_raw: bytes | None, outcome_raw: bytes | None,
                                    assessment_raw: bytes | None, protocol_raw: bytes | None, *,
                                    now: datetime) -> dict:
    if now.utcoffset() is None:
        raise ValueError("AWARE_CLOCK_REQUIRED")
    try:
        pilot = _pilot(frozen_raw, outcome_raw, assessment_raw, now=now)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        pilot = {"status": "INVALID", "reason": "Retained pilot receipt or observation clock failed validation."}
    try:
        cohort = _cohort(protocol_raw, now=now)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        cohort = {"status": "INVALID", "reason": "Protocol pin, schema or registration clock failed validation."}
    return {
        "scope": "RETAINED_PUBLIC_CONTROL_NOT_PRIVATE_EVENT_LEDGER",
        "evaluated_at": now.isoformat(), "pilot": pilot, "cohort": cohort,
        "model_validation_status": "NOT_VALIDATED", "probability_calibrated": False,
        "private_event_chain_verified": False, "original_vendor_bytes_verified": False,
        "research_only": True, "execution_allowed": False, "decision_authority": False,
        "model_promotion_allowed": False,
    }


def read_prediction_observations(pilot_dir: Path, protocol_path: Path, *, now: datetime) -> dict:
    # The caller supplies fixed, approved paths, never request-derived paths.
    # Isolate an unreadable/tampered file from the other independent section.
    def read_or_invalid(path):
        try:
            return _read(path)
        except (ValueError, OSError):
            return b""
    return project_prediction_observations(
        *(read_or_invalid(pilot_dir / name) for name in
          ("FROZEN_RECEIPT.json", "OUTCOME_RECEIPT.json", "ASSESSMENT_RECEIPT.json")),
        read_or_invalid(protocol_path), now=now,
    )
