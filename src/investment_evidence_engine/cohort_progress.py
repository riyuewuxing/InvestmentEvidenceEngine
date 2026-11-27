"""Read-only progress of a fixed prospective protocol; never an activation path.

Absence of a receipt does not establish absence of an attempt. A terminal
record is never eligible for retry, including missing observations. Neither
this module nor its descriptive assessment authenticates external provenance.
The preregistered protocol, capture, scoring and historical receipts are unchanged.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .prospective_diagnostics import assess_paired_direction_delta
from .prospective_protocol import (
    CohortBatchRecord,
    CohortProtocol,
    assess_registered_cohort,
    deadline,
    maturity,
    planning_start,
)


def describe_cohort_progress(
    protocol: CohortProtocol,
    records: tuple[CohortBatchRecord, ...],
    *,
    expected_protocol_sha256: str,
    now: datetime,
) -> dict:
    """Expose window and missingness states without manufacturing observations."""
    assessment = assess_registered_cohort(
        protocol, records, expected_protocol_sha256=expected_protocol_sha256, now=now
    )
    by_session = {r.batch.session: r for r in records}
    receipt_hashes = [
        digest
        for record in records
        for digest in (record.freeze_receipt_sha256, record.outcome_receipt_sha256)
        if digest is not None
    ]
    if len(receipt_hashes) != len(set(receipt_hashes)):
        raise ValueError("COHORT_PROGRESS_RECEIPT_REUSE")
    sessions = []
    for day in protocol.sessions():
        record = by_session.get(day)
        start = planning_start(day)
        end = start + timedelta(days=1)
        selected = evaluated = 0
        if record is None:
            if now < start:
                state = "WAITING_FOR_PLANNING"
            elif now < end:
                state = "PLANNING_WINDOW_OPEN_NO_RECEIPT"
            else:
                state = "FREEZE_WINDOW_CLOSED_NO_RECEIPT"
        else:
            rows = record.batch.rows
            selected = sum(row.disposition == "SELECTED" for row in rows)
            evaluated = sum(
                row.disposition == "SELECTED" and row.outcome_status == "OBSERVED"
                for row in rows
            )
            if record.outcome_receipt_sha256 is None:
                if now < maturity(day):
                    state = "WAITING_FOR_OBSERVATION"
                elif now <= deadline(day):
                    state = "SETTLEMENT_WINDOW_OPEN_NO_RECEIPT"
                else:
                    state = "SETTLEMENT_WINDOW_CLOSED_NO_RECEIPT"
            elif evaluated == 0:
                state = "TERMINAL_UNEVALUABLE"
            elif evaluated != len(protocol.symbols):
                state = "TERMINAL_PARTIAL"
            else:
                state = "TERMINAL_COMPLETE_PAIRED"
        sessions.append({
            "session": day.isoformat(),
            "state": state,
            "planning_start": start.isoformat(),
            "planning_end_exclusive": end.isoformat(),
            "observation_maturity": maturity(day).isoformat(),
            "settlement_deadline_inclusive": deadline(day).isoformat(),
            "selected": selected if record is not None else None,
            "evaluable": evaluated if record is not None else None,
            "freeze_receipt_sha256": record.freeze_receipt_sha256 if record else None,
            "outcome_receipt_sha256": record.outcome_receipt_sha256 if record else None,
        })
    matured = tuple(day for day in protocol.sessions() if maturity(day) <= now)
    paired = assess_paired_direction_delta(
        protocol.first, matured[-1], protocol.symbols,
        tuple(record.batch for record in records if record.batch.session in matured),
        now=now,
    ) if matured else None
    return {
        "protocol_sha256": assessment["protocol_sha256"],
        "status": (
            "WAITING_FOR_OBSERVATION"
            if not assessment["final_settlement_window_closed"]
            else "INTERVAL_CLOSED_DESCRIPTIVE_ONLY"
        ),
        "evaluated_at": now.isoformat(),
        "sessions": sessions,
        "assessment": assessment,
        "paired_direction_diagnostics": paired,
        "model_validation_status": "NOT_VALIDATED",
        "probability_calibrated": False,
        "first_attempt_provenance_verified": False,
        "source_bytes_verified": False,
        "activation_authorized": False,
        "retry_authorized": False,
        "backfill_authorized": False,
        "research_only": True,
        "execution_allowed": False,
    }
