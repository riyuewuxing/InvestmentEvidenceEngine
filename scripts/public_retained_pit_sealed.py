"""Offline sealed execution of actual, locally re-opened BLS source projections.

The source rows are not claimed to be authenticated remote operations or
historical first-availability witnesses. This validates actual public-runner
request sealing, multi-dependency artifact binding, propagation and result sealing.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from public_retained_pit_dependency import run_control

from investment_evidence_engine.contracts import ExecutionOperation, ExecutionRequest, ExecutionResult
from investment_evidence_engine.runner import execute_request


def run_sealed_control(repo: str, commit: str) -> dict:
    source = run_control()
    rows = source["source_rows"]
    historical = "2025-12-16T08:30:00-05:00"
    first = rows[0]["durable_verified_at"]
    last = rows[-1]["durable_verified_at"]
    results = []
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        for label, cutoff, expected_upstream, expected_downstream in (
            ("historical", historical, ["BLOCK", "BLOCK", "BLOCK"], "BLOCK"),
            ("first-durable", first, ["WARN", "BLOCK", "BLOCK"], "BLOCK"),
            ("last-durable", last, ["WARN", "WARN", "WARN"], "WARN"),
        ):
            ops = [
                ExecutionOperation(operation_id=f"source-{index}", kind="PIT_REPLAY",
                                   parameters={"as_of": cutoff, "inline_records": [row], "strict": True})
                for index, row in enumerate(rows)
            ]
            deps = [op.operation_id for op in ops]
            ops.append(ExecutionOperation(
                operation_id="merged-replay", kind="PIT_REPLAY",
                parameters={"as_of": cutoff, "depends_on_operation_ids": deps, "strict": True},
            ))
            req = ExecutionRequest(
                job_id=f"retained-sealed-{label}", trace_id=f"retained-sealed-{label}",
                subject_repo=repo, subject_commit=commit, as_of=cutoff, operations=ops,
            )
            req.request_sha256 = req.compute_hash()
            req_path = root / f"{label}.json"
            req_path.write_text(req.model_dump_json(), encoding="utf-8")
            out = root / label
            res = execute_request(req_path, output_dir=out, executor_repo=repo, executor_commit=commit)
            if [op.status for op in res.operations] != [*expected_upstream, expected_downstream]:
                raise ValueError("SEALED_PIT_STATUS_MISMATCH")
            reopened = ExecutionResult.model_validate_json((out / "execution_result.json").read_bytes())
            if reopened.compute_hash() != res.result_sha256 or reopened.request_sha256 != req.request_sha256:
                raise ValueError("SEALED_PIT_HASH_MISMATCH")
            manifest = json.loads((out / "run_manifest.json").read_bytes())
            if (manifest["request_sha256"] != req.request_sha256
                    or manifest["result_sha256"] != res.result_sha256
                    or manifest["decision_authority"] is not False):
                raise ValueError("SEALED_PIT_MANIFEST_MISMATCH")
            hashes = {}
            for ref in manifest["artifacts"]:
                raw = (out / ref["path"]).read_bytes()
                if (hashlib.sha256(raw).hexdigest() != ref["sha256"]
                        or len(raw) != ref["size_bytes"]):
                    raise ValueError("SEALED_PIT_ARTIFACT_MISMATCH")
                hashes[ref["path"]] = ref["sha256"]
            downstream = res.operations[-1]
            if expected_downstream == "WARN":
                merged = json.loads((out / "merged-replay.json").read_bytes())
                if (merged["eligible_count"] != 3
                        or merged["eligible_input_indices"] != [0, 1, 2]
                        or merged["pit_safe"] is not False
                        or merged["historical_vintage_verified"] is not False
                        or merged["decision_authority"] is not False):
                    raise ValueError("SEALED_PIT_MERGE_MISMATCH")
                for dep in deps:
                    if merged["input_scope"]["dependency_artifacts"][dep]["artifact_sha256"] != hashes[dep + ".json"]:
                        raise ValueError("SEALED_PIT_DEPENDENCY_HASH")
                indices = merged["eligible_input_indices"]
            else:
                if downstream.artifacts or not any(e.startswith("UPSTREAM_NOT_USABLE:") for e in downstream.errors):
                    raise ValueError("SEALED_PIT_FAILED_TO_PROPAGATE_BLOCK")
                indices = []
            results.append({
                "case": label, "cutoff": cutoff, "status": res.status,
                "operations": manifest["operation_statuses"], "merged_eligible_indices": indices,
                "request_sha256": req.request_sha256, "result_sha256": res.result_sha256,
                "artifact_hashes": hashes, "artifact_rehash": "MATCH",
            })
    return {
        "status": "WARN", "executor_repo": repo, "executor_commit": commit,
        "source_files_reopened": source["source_files_reopened"],
        "sealed_runner_transport_verified": True, "source_projections_inline": True,
        "historical_vintage_verified": False, "historical_first_availability_verified": False,
        "pit_safe": False, "decision_authority": False, "execution_allowed": False,
        "network_requests": 0, "cases": results,
    }


if __name__ == "__main__":
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    report = run_sealed_control(repo, os.environ["GITHUB_SHA"])
    print("PUBLIC_RETAINED_PIT_SEALED " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
