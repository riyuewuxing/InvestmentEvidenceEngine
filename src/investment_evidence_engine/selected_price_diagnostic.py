"""Use exactly the first observed public scan record for a price-only diagnostic.

The selected symbol is an ex-post cohort member. This never asserts historical
selection feasibility, a source graph, a PIT research profile, or advice.
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .contracts import ExecutionOperation, ExecutionRequest, canonical_sha256
from .input_binding import select_scan_record
from .listing_comparison import stock_code
from .retrospective_control import retrospective_momentum
from .runner import execute_request
from .snapshot_integrity import strict_json_loads
from .transport_integrity import observe_artifact_file, read_contract_bytes

FIRST = date(2025, 1, 2)
SCOPE = date(2026, 11, 26)


def verify_selection(raw: bytes, receipt: dict, reference: list[str]) -> str:
    if (receipt.get("status") != "PUBLIC_PACKET_AND_ATTACHMENT_REHASHED"
            or receipt.get("as_of") != SCOPE.isoformat()
            or receipt.get("deterministic_scan_replay") != "MATCH"
            or receipt.get("materialized_attachment_rehash") != "MATCH"
            or receipt.get("decision_authority") is not False
            or receipt.get("private_admission_verified") is not False):
        raise ValueError("SELECTED_DIAGNOSTIC_PACKET_RECEIPT_INVALID")
    ref = receipt["artifacts"]["opportunity-scan.json"]
    if (hashlib.sha256(raw).hexdigest(), len(raw)) != (ref["sha256"], ref["size_bytes"]):
        raise ValueError("SELECTED_DIAGNOSTIC_SCAN_BYTES_MISMATCH")
    selected = select_scan_record(raw, SCOPE.isoformat())
    if canonical_sha256(selected) != receipt["candidate_record_sha256"]:
        raise ValueError("SELECTED_DIAGNOSTIC_RECORD_MISMATCH")
    code = selected["code"]
    if stock_code(code, require_exchange=False) not in set(reference):
        raise ValueError("SELECTED_DIAGNOSTIC_FIRST_RECORD_OUTSIDE_REFERENCE")
    return code


def evaluate_market_payload(payload: object, *, symbol: str) -> dict:
    end = SCOPE - timedelta(days=1)
    if (not isinstance(payload, dict)
            or (payload.get("symbol"), payload.get("start"), payload.get("end"),
                payload.get("as_of"), payload.get("adjust"))
            != (symbol, FIRST.isoformat(), end.isoformat(), SCOPE.isoformat(), "")
            or payload.get("history_end_offset_days") != 1
            or payload.get("pit_safe") is not False
            or payload.get("decision_authority") is not False
            or payload.get("historical_vintage_verified") is not False):
        raise ValueError("SELECTED_DIAGNOSTIC_MARKET_SCOPE")
    crosscheck = payload.get("crosscheck")
    if (not isinstance(crosscheck, dict) or crosscheck.get("status") != "MATCH_OBSERVED_ROWS"
            or crosscheck.get("tolerance") != 0.001
            or crosscheck.get("latest_common_date") != end.isoformat()
            or crosscheck.get("left_only_dates") != 0 or crosscheck.get("right_only_dates") != 0):
        raise ValueError("SELECTED_DIAGNOSTIC_PRICE_CROSSCHECK_REQUIRED")
    providers = payload.get("providers")
    if not isinstance(providers, list):
        raise ValueError("SELECTED_DIAGNOSTIC_PROVIDER_RECEIPTS")
    observed = [p for p in providers if p.get("status") == "OBSERVED"]
    if (len(observed) != 2 or len({p["upstream"] for p in observed}) != 2
            or not any(p["upstream"] == "tencent" and p.get("raw_body_parent_rehash") == "MATCH"
                       for p in observed)):
        raise ValueError("SELECTED_DIAGNOSTIC_RAW_TENCENT_REQUIRED")
    bars = payload.get("bars")
    if not isinstance(bars, list) or len(bars) != crosscheck.get("overlap_rows"):
        raise ValueError("SELECTED_DIAGNOSTIC_BAR_COUNT_MISMATCH")
    return retrospective_momentum(pd.DataFrame(bars), FIRST, end)


def run_selected_price_diagnostic(raw: bytes, receipt: dict, reference: list[str], *,
                                  root: Path, repo: str, commit: str) -> dict:
    report = {"status": "BLOCK", "selection": "EXACT_FIRST_CURRENT_SCAN_RECORD",
              "candidate_record_sha256": receipt.get("candidate_record_sha256"),
              "historical_selection_verified": False, "source_graph_verified": False,
              "decision_authority": False, "execution_allowed": False,
              "private_admission_verified": False, "pit_safe": False}
    try:
        symbol = verify_selection(raw, receipt, reference)
        report["public_control_symbol"] = symbol
        end = SCOPE - timedelta(days=1)
        # An independent market request, linked in this local diagnostic by
        # observed scan bytes. Do not fake a private InputArtifactRef graph.
        request = ExecutionRequest(
            job_id="selected-price-" + receipt["candidate_record_sha256"][:16],
            trace_id="selected-price-" + receipt["request_sha256"][:16],
            subject_repo=repo, subject_commit=commit, as_of=SCOPE.isoformat(),
            operations=[ExecutionOperation(operation_id="selected-market", kind="MARKET_DATA",
                parameters={"subject_ids": [symbol], "as_of": SCOPE.isoformat(), "adjust": "",
                            "history_days": (end-FIRST).days, "history_end_offset_days": 1,
                            "price_tolerance": 0.001}, expected_outputs=["selected-market.json"],
                evidence_domains=["MARKET"])])
        request.request_sha256 = request.compute_hash()
        root.mkdir()
        req = root / "request.json"
        req.write_text(request.model_dump_json(), encoding="utf-8")
        output = root / "out"
        result = execute_request(req, output_dir=output, executor_repo=repo, executor_commit=commit)
        item = result.operations[0]
        report |= {"market_request_sha256": request.request_sha256, "market_result_sha256": result.result_sha256,
                   "market_status": item.status, "market_metrics": item.metrics,
                   "market_warnings": item.warnings, "market_errors": item.errors}
        if item.status != "WARN" or len(item.artifacts) != 1:
            return report
        ref = item.artifacts[0]
        digest, size = observe_artifact_file(output, ref.path, ref.size_bytes)
        if (digest, size) != (ref.sha256, ref.size_bytes):
            raise ValueError("SELECTED_DIAGNOSTIC_MARKET_DIGEST")
        data = read_contract_bytes(output / ref.path)
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("SELECTED_DIAGNOSTIC_MARKET_BYTES_CHANGED")
        payload = strict_json_loads(data)
        report |= {"market_artifact_sha256": digest, "market_artifact_size": size,
                   "market_artifact_rehash": "MATCH", "providers": payload.get("providers"),
                   "crosscheck": payload.get("crosscheck")}
        report["diagnostic"] = evaluate_market_payload(payload, symbol=symbol)
        report["status"] = "WARN"
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as exc:
        report["blocker"] = (str(exc) if str(exc).startswith(("SELECTED_DIAGNOSTIC_", "RETROSPECTIVE_"))
                             else type(exc).__name__)
    return report
