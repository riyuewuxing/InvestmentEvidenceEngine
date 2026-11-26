from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

import pytest

from investment_evidence_engine.prospective_capture import (
    activation_path,
    build_receipt,
    calendar_expected,
    expected_inputs,
    receipt_sha256,
    to_batch_record,
    validate_marker,
    vendor_symbol,
    verify_receipt,
)
from investment_evidence_engine.prospective_protocol import (
    CohortProtocol,
    assess_registered_cohort,
    maturity,
    planning_start,
    protocol_sha256,
)

P = CohortProtocol.model_validate_json(
    (Path(__file__).resolve().parents[1] / "pilot-protocols/public-daily-20261130-v1.json").read_text()
)
TARGET = date(2026, 11, 30)
FREEZE = planning_start(TARGET)+timedelta(hours=8)
SETTLE = maturity(TARGET)


def make_rows(symbol, sessions, close="10.10", status="1"):
    return [[d, vendor_symbol(symbol), "10", close, "100", "3", status] for d in sessions]


def observations(phase):
    days = expected_inputs(TARGET) if phase == "freeze" else [TARGET.isoformat()]
    return {s: {"rows": make_rows(s, days)} for s in P.symbols}


def freeze(data=None):
    return build_receipt(P, TARGET, "freeze", observations("freeze") if data is None else data,
                         started=FREEZE, observed=FREEZE, calendar=calendar_expected(TARGET))


def settle(data=None):
    return build_receipt(P, TARGET, "settle", observations("settle") if data is None else data,
                         started=SETTLE, observed=SETTLE)


def test_end_to_end_synthetic_receipt_and_assessment():
    f, o = freeze(), settle()
    assert f["input_end"] == "2026-11-28"
    assert expected_inputs(TARGET)[-1] == "2026-11-27"
    assert [x["direction"] for x in f["rows"]] == ["UP", "UP"]
    r = to_batch_record(P, f, frozen_sha256=receipt_sha256(f), outcome=o,
                        outcome_sha256=receipt_sha256(o))
    report = assess_registered_cohort(P, (r,), expected_protocol_sha256=protocol_sha256(P), now=SETTLE)
    assert report["assessment"]["observed_selected_accuracy"] == 1
    assert report["assessment"]["expected_subject_session_slots"] == 2
    assert report["expected_slots_full_interval"] == 40


def test_member_unavailability_preserved():
    data = observations("freeze")
    data[P.symbols[0]] = {"error": "TimeoutError"}
    data[P.symbols[1]]["rows"][0][1] = "sh.999999"
    f = freeze(data)
    assert [x["disposition"] for x in f["rows"]] == ["UNAVAILABLE", "UNAVAILABLE"]
    assert f["observations"][P.symbols[0]]["error"] == "TimeoutError"
    verify_receipt(P, f, expected_sha256=receipt_sha256(f))
    pending = to_batch_record(P, f, frozen_sha256=receipt_sha256(f))
    assert all(row.outcome_status == "PENDING" for row in pending.batch.rows)


def test_outcome_missing_and_suspended_not_flat():
    data = observations("settle")
    data[P.symbols[0]] = {"rows": []}
    data[P.symbols[1]]["rows"][0][-1] = "0"
    f, o = freeze(), settle(data)
    r = to_batch_record(P, f, frozen_sha256=receipt_sha256(f), outcome=o,
                        outcome_sha256=receipt_sha256(o))
    assert [x.outcome_status for x in r.batch.rows] == ["UNAVAILABLE", "UNTRADEABLE"]
    assert all(x.observed_return is None for x in r.batch.rows)


def test_exact_member_calendar_and_window_guards():
    data = observations("freeze")
    del data[P.symbols[0]]
    with pytest.raises(ValueError):
        freeze(data)
    with pytest.raises(ValueError):
        build_receipt(P, TARGET, "freeze", observations("freeze"), started=FREEZE, observed=FREEZE, calendar=[])
    with pytest.raises(ValueError):
        build_receipt(P, TARGET, "settle", observations("settle"),
                      started=SETTLE-timedelta(seconds=1), observed=SETTLE)


def test_tampering_and_hash_mismatch():
    f = freeze()
    changed = deepcopy(f)
    changed["rows"][0]["direction"] = "DOWN"
    with pytest.raises(ValueError):
        verify_receipt(P, changed, expected_sha256=receipt_sha256(changed))
    with pytest.raises(ValueError):
        verify_receipt(P, f, expected_sha256="0"*64)


def test_future_or_wrong_symbol_row_is_unavailable():
    data = observations("freeze")
    data[P.symbols[0]]["rows"][-1][0] = TARGET.isoformat()
    f = freeze(data)
    assert f["rows"][0]["disposition"] == "UNAVAILABLE"
    assert f["rows"][1]["disposition"] == "SELECTED"


def test_activation_single_new_marker_only():
    path = "pilot-triggers/" + P.protocol_id + "--freeze--2026-11-30.txt"
    encoded = b"A\0" + path.encode() + b"\0"
    assert activation_path(P, encoded) == (path, "freeze", TARGET)
    validate_marker(P, "freeze", TARGET, f"{P.protocol_id} freeze {TARGET}\n".encode())
    for bad in (encoded.replace(b"A\0", b"M\0"), encoded+encoded,
                encoded.replace(b"11-30", b"11-29"), encoded.replace(b"pilot-triggers/", b"../")):
        with pytest.raises(ValueError):
            activation_path(P, bad)
    with pytest.raises(ValueError):
        validate_marker(P, "freeze", TARGET, b"unexpected")
