"""Reopen actual public scan outputs. Integrity and replay, not private admission."""
from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from .contracts import ExecutionRequest, ExecutionResult, canonical_sha256
from .dispatch import run_operation
from .input_binding import select_scan_record
from .snapshot_integrity import strict_json_loads
from .transport_integrity import observe_artifact_file, read_contract_bytes, result_transport_errors
from .workers import WorkerContext


def verify_public_scan_packet(root: Path, *, repo: str, commit: str) -> tuple[dict, dict, list[str], bytes]:
    request = ExecutionRequest.model_validate(strict_json_loads(read_contract_bytes(root / "execution_request.json")))
    result = ExecutionResult.model_validate(strict_json_loads(read_contract_bytes(root / "execution_result.json")))
    manifest_raw = read_contract_bytes(root / "run_manifest.json")
    manifest = strict_json_loads(manifest_raw)
    if (not request.verify() or result.compute_hash() != result.result_sha256
            or result.request_sha256 != request.request_sha256
            or (request.subject_repo, request.subject_commit) != (repo, commit)
            or (result.subject_repo, result.subject_commit) != (repo, commit)
            or (result.executor.repo, result.executor.commit) != (repo, commit)
            or (request.job_id, request.trace_id) != (result.job_id, result.trace_id)
            or request.input_artifacts or result.observed_input_artifacts
            or result.status not in {"PASS", "WARN"}):
        raise ValueError("PUBLIC_SCAN_PACKET_IDENTITY_OR_HASH")
    if [(op.operation_id, op.kind) for op in request.operations] != [
            ("market-universe", "MARKET_UNIVERSE"), ("opportunity-scan", "OPPORTUNITY_SCAN")]:
        raise ValueError("PUBLIC_SCAN_PACKET_CHAIN")
    if result_transport_errors([op.model_dump(mode="json") for op in request.operations],
                               [op.model_dump(mode="json") for op in result.operations], result.status):
        raise ValueError("PUBLIC_SCAN_PACKET_TRANSPORT")
    expected = {"job_id": result.job_id, "trace_id": result.trace_id,
                "subject_repo": repo, "subject_commit": commit, "executor_repo": repo,
                "executor_commit": commit, "request_sha256": result.request_sha256,
                "result_sha256": result.result_sha256, "status": result.status,
                "operation_statuses": {op.operation_id: op.status for op in result.operations},
                "artifacts": [ref.model_dump(mode="json") for op in result.operations for ref in op.artifacts],
                "decision_authority": False}
    if manifest != expected:
        raise ValueError("PUBLIC_SCAN_MANIFEST_MISMATCH")
    if [tuple(ref.path for ref in op.artifacts) for op in result.operations] != [
            ("market-universe.json",), ("opportunity-scan.json",)]:
        raise ValueError("PUBLIC_SCAN_ARTIFACT_SET_MISMATCH")
    artifact_digests = {}
    for op in result.operations:
        for ref in op.artifacts:
            digest, size = observe_artifact_file(root, ref.path, ref.size_bytes)
            if digest != ref.sha256 or size != ref.size_bytes:
                raise ValueError("PUBLIC_SCAN_ARTIFACT_HASH_MISMATCH")
            artifact_digests[ref.path] = {"sha256": digest, "size_bytes": size}
    raw = read_contract_bytes(root / "opportunity-scan.json")
    selected = select_scan_record(raw, request.as_of)
    universe = strict_json_loads(read_contract_bytes(root / "market-universe.json"))
    if not isinstance(universe, dict) or not isinstance(universe.get("records"), list):
        raise ValueError("PUBLIC_SCAN_UNIVERSE_RECORDS")
    codes = [row["code"] for row in universe["records"]]
    # Independent reread and deterministic replay of the production scanner
    # on the exact saved universe, without another provider request.
    with TemporaryDirectory() as temp:
        ctx = WorkerContext(output_dir=Path(temp), request_as_of=request.as_of)
        ctx.payloads["market-universe"] = universe
        ctx.completed_operations["market-universe"] = {
            "kind": "MARKET_UNIVERSE", "status": result.operations[0].status,
            "as_of": request.as_of, "market": "CN_A", "asset_type": "STOCK"}
        replay = run_operation(request.operations[1], ctx)
        replay_raw = (Path(temp) / "opportunity-scan.json").read_bytes()
        if replay.status != result.operations[1].status or replay_raw != raw:
            raise ValueError("PUBLIC_SCAN_REPLAY_MISMATCH")
        # Exercise the exact attachment bytes without fabricating a private
        # graph digest or uploading vendor-derived candidate records.
        attached = Path(temp) / "requests/inputs/scan.json"
        attached.parent.mkdir(parents=True)
        attached.write_bytes(raw)
        digest, size = observe_artifact_file(Path(temp), "requests/inputs/scan.json", len(raw))
        if (digest != artifact_digests["opportunity-scan.json"]["sha256"] or size != len(raw)
                or select_scan_record(attached.read_bytes(), request.as_of) != selected):
            raise ValueError("PUBLIC_SCAN_ATTACHMENT_MISMATCH")
    receipt = {"status": "PUBLIC_PACKET_AND_ATTACHMENT_REHASHED",
               "request_sha256": request.request_sha256, "result_sha256": result.result_sha256,
               "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
               "artifacts": artifact_digests, "candidate_record_sha256": canonical_sha256(selected),
               "deterministic_scan_replay": "MATCH", "materialized_attachment_rehash": "MATCH",
               "as_of": request.as_of, "source_graph_verified": False,
               "private_admission_verified": False, "pit_safe": False, "decision_authority": False}
    return receipt, selected, codes, raw
