"""Actual retained public-domain originals through production PIT_REPLAY.

No network, no private data, no backdated knowledge. Source operations in
this control are explicitly local projections of independently reopened PDFs,
not remote sealed executor jobs. The new proof is dependency byte binding.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from replay_bls_archive import retained_revisions

from investment_evidence_engine.contracts import ArtifactRef, ExecutionOperation
from investment_evidence_engine.dispatch import run_operation
from investment_evidence_engine.snapshot_integrity import strict_json_loads
from investment_evidence_engine.transport_integrity import read_verified_artifact
from investment_evidence_engine.workers import WorkerContext


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def run_control() -> dict:
    revisions = retained_revisions()
    rows = []
    for rev in revisions:
        rows.append({"series_id": rev.series_id, "period": rev.period, "unit": rev.unit,
                     "version_id": rev.revision_id, "predecessor_id": rev.predecessor_id,
                     "value": str(rev.value), "original_document_sha256": rev.raw_sha256,
                     "declared_release_at": rev.declared_release_at.isoformat(),
                     # Historical release is not the observed availability time.
                     "available_at": rev.observed_at.isoformat(),
                     "retrieved_at": rev.observed_at.isoformat(),
                     "observed_at": rev.observed_at.isoformat(),
                     "durable_verified_at": rev.durable_verified_at.isoformat(),
                     "availability_basis": "FIRST_SYSTEM_CAPTURE_KNOWN_IN_THIS_ARCHIVE",
                     "historical_first_availability_verified": False,
                     "historical_vintage_verified": False})
    with TemporaryDirectory() as temp:
        ctx = WorkerContext(output_dir=Path(temp))
        deps = []
        for index, row in enumerate(rows):
            dep = f"retained-source-{index}"
            deps.append(dep)
            payload = {"records": [row], "source_projection": "REOPENED_PINNED_PUBLIC_DOMAIN_ORIGINAL",
                       "pit_safe": False, "decision_authority": False}
            raw = json.dumps(payload, sort_keys=True, allow_nan=False).encode()
            path = ctx.output_dir / (dep + ".json")
            path.write_bytes(raw)
            ref = ArtifactRef(path=path.name, sha256=sha(raw), size_bytes=len(raw),
                              media_type="application/json")
            ctx.payloads[dep] = payload
            ctx.completed_operations[dep] = {"kind": "OFFICIAL_SOURCE", "status": "WARN",
                                              "artifact_refs": [ref.model_dump(mode="json")]}

        def replay(label, cutoff, ids, expected, count):
            ctx.request_as_of = cutoff.isoformat()
            op = ExecutionOperation(operation_id=label, kind="PIT_REPLAY",
                parameters={"as_of": cutoff.isoformat(), "depends_on_operation_ids": ids, "strict": True})
            result = run_operation(op, ctx)
            if result.status != expected or result.metrics.get("eligible_count") != count:
                raise ValueError("RETAINED_PIT_EXPECTED_BOUNDARY")
            ref = result.artifacts[0]
            body = read_verified_artifact(ctx.output_dir, ref.path, ref.sha256, ref.size_bytes)
            parsed = strict_json_loads(body)
            if (parsed["pit_safe"] is not False or parsed["decision_authority"] is not False
                    or parsed["historical_vintage_verified"] is not False):
                raise ValueError("RETAINED_PIT_UNAUTHORIZED_PROMOTION")
            scope = parsed["input_scope"]["dependency_artifacts"]
            if set(scope) != set(ids) or any(x["artifact_rehash"] != "MATCH" for x in scope.values()):
                raise ValueError("RETAINED_PIT_DEPENDENCY_SCOPE")
            return {"case": label, "cutoff": cutoff.isoformat(), "status": result.status,
                    "errors": result.errors, "eligible_count": count,
                    "eligible_indices": parsed["eligible_input_indices"],
                    "eligible_versions": [r["version_id"] for r in parsed["eligible_records"]],
                    "dependency_artifacts": scope, "result_artifact_sha256": ref.sha256}

        first, final = revisions[0].durable_verified_at, revisions[-1].durable_verified_at
        cases = [
            replay("historical-cutoff", revisions[-1].declared_release_at, deps, "BLOCK", 0),
            replay("before-first-durable", first - timedelta(microseconds=1), deps[:1], "BLOCK", 0),
            replay("first-durable", first, deps[:1], "WARN", 1),
            replay("full-set-at-first-durable", first, deps, "BLOCK", 1),
            replay("before-last-durable", final - timedelta(microseconds=1), deps, "BLOCK", 1),
            replay("full-set-at-last-durable", final, deps, "WARN", 3),
        ]
        # Alter the real normalized projection while leaving the retained source
        # file and its declared hash intact. The production dependency gate must
        # reject before considering the timestamps.
        ctx.payloads[deps[1]]["records"][0]["value"] = "0"
        op = ExecutionOperation(operation_id="tamper-control", kind="PIT_REPLAY",
            parameters={"as_of": final.isoformat(), "depends_on_operation_ids": deps})
        result = run_operation(op, ctx)
        if (result.status != "BLOCK" or result.errors != ["PIT_REPLAY_DEPENDENCY_CONTEXT_MISMATCH"]
                or result.artifacts):
            raise ValueError("RETAINED_PIT_TAMPER_NOT_REJECTED")
    return {"status": "WARN", "source": "BLS_ARCHIVE_VIA_FRASER", "source_files_reopened": len(rows),
            "source_rows": rows, "cases": cases, "tamper": result.errors,
            "network_requests": 0, "source_operations_are_local_projections": True,
            "full_remote_executor_chain_verified": False,
            "historical_vintage_verified": False, "first_public_availability_verified": False,
            "pit_safe": False, "decision_authority": False, "execution_allowed": False}


if __name__ == "__main__":
    if os.environ.get("GITHUB_REPOSITORY") != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    report = run_control() | {"executor_commit": os.environ["GITHUB_SHA"]}
    print("PUBLIC_RETAINED_PIT_DEPENDENCY " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
