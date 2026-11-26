"""Run a real retained archive through the sealed existing public engine runner."""
import base64
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from investment_evidence_engine.contracts import ExecutionOperation, ExecutionRequest
from investment_evidence_engine.runner import execute_request
from investment_evidence_engine.twse_archive_industry import DIGEST, PROFILE, VERIFIED

REPO = "riyuewuxing/InvestmentEvidenceEngine"


def exercise(cutoff, *, emit_packet=False):
    commit = os.environ["GITHUB_SHA"]
    stamp = cutoff.isoformat()
    op = ExecutionOperation(operation_id="industry", kind="INDUSTRY_MACRO",
        parameters={"industry_profile": PROFILE, "archive_sha256": DIGEST, "market": "TWSE",
                    "subject_ids": ["TWSE:2330"], "as_of": stamp},
        evidence_domains=["INDUSTRY_MACRO"])
    req = ExecutionRequest(job_id="twse-archive-industry-control", trace_id="twse-archive-industry-202610",
        subject_repo=REPO, subject_commit=commit, as_of=stamp, operations=[op])
    req.request_sha256 = req.compute_hash()
    with TemporaryDirectory() as folder:
        root = Path(folder)
        request_path = root / "request.json"
        request_path.write_text(req.model_dump_json(indent=2), encoding="utf-8")
        output = root / "out"
        result = execute_request(request_path, output_dir=output, executor_repo=REPO,
                                 executor_commit=commit)
        if result.compute_hash() != result.result_sha256 or result.request_sha256 != req.request_sha256:
            raise ValueError("TWSE_SEALED_RESULT_MISMATCH")
        report = {"status": result.status, "request_sha256": req.request_sha256,
                  "result_sha256": result.result_sha256,
                  "errors": result.operations[0].errors, "executor_commit": commit}
        if result.status == "WARN":
            artifacts = result.operations[0].artifacts
            if len(artifacts) != 1 or artifacts[0].path != "industry.json":
                raise ValueError("TWSE_ARTIFACT_SCOPE")
            raw = (output / "industry.json").read_bytes()
            if hashlib.sha256(raw).hexdigest() != artifacts[0].sha256 or len(raw) != artifacts[0].size_bytes:
                raise ValueError("TWSE_ARTIFACT_REHASH")
            report |= {"artifact_sha256": artifacts[0].sha256, "artifact_bytes": len(raw),
                       "payload": json.loads(raw), "artifact_parent_rehash": "MATCH"}
            if emit_packet:
                names = ("execution_request.json", "execution_result.json", "run_manifest.json", "industry.json")
                packet = {}
                for name in names:
                    path = output / name
                    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 65536:
                        raise ValueError("TWSE_PACKET_FILE_SCOPE")
                    with path.open("rb") as handle:
                        body = handle.read(65537)
                    if not 0 < len(body) <= 65536:
                        raise ValueError("TWSE_PACKET_FILE_SCOPE")
                    if name == "industry.json" and body != raw:
                        raise ValueError("TWSE_PACKET_ARTIFACT_CHANGED")
                    encoded = base64.b64encode(body).decode("ascii")
                    packet[name] = {"sha256": hashlib.sha256(body).hexdigest(),
                                    "bytes": len(body), "base64_chars": len(encoded),
                                    "chunks": (len(encoded)+4095)//4096}
                    for i in range(0, len(encoded), 4096):
                        print(f"TWSE_PACKET_BYTES {name} {i//4096:04d} {encoded[i:i+4096]}", flush=True)
                report["packet_files"] = packet
        return report


if __name__ == "__main__":
    if os.environ["GITHUB_REPOSITORY"] != REPO:
        raise SystemExit("public repository required")
    prior = exercise(VERIFIED-timedelta(microseconds=1))
    actual = exercise(datetime.now(UTC), emit_packet=True)
    report = {"prior_cutoff": prior, "observed_replay": actual,
              "decision_authority": False, "execution_allowed": False}
    print("TWSE_ARCHIVE_INDUSTRY_CONTROL " + json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    if prior["status"] != "BLOCK" or actual["status"] != "WARN":
        raise SystemExit(2)
