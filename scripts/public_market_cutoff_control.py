"""Real public-only control; never publish raw vendor records or account state."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from investment_evidence_engine.contracts import ExecutionOperation, ExecutionRequest
from investment_evidence_engine.runner import execute_request

scope = datetime.now(ZoneInfo("Asia/Shanghai")).date()
cutoff = scope - timedelta(days=1)
repo = os.environ["GITHUB_REPOSITORY"]
sha = os.environ["GITHUB_SHA"]
request = ExecutionRequest(
    job_id="public-market-offset-control",
    trace_id="public-market-offset-control",
    subject_repo=repo,
    subject_commit=sha,
    as_of=scope.isoformat(),
    operations=[ExecutionOperation(
        operation_id="market",
        kind="MARKET_DATA",
        parameters={"as_of": scope.isoformat(), "subject_ids": ["600519"],
                    "adjust": "", "history_days": 60, "history_end_offset_days": 1},
        evidence_domains=["MARKET"],
        expected_outputs=["market.json"],
    )],
)
request.request_sha256 = request.compute_hash()
with TemporaryDirectory() as temp:
    root = Path(temp)
    req = root / "request.json"
    req.write_text(request.model_dump_json(), encoding="utf-8")
    out = root / "out"
    result = execute_request(req, output_dir=out, executor_repo=repo, executor_commit=sha)
    item = result.operations[0]
    summary = {"executor_commit": sha, "request_sha256": request.request_sha256,
               "result_sha256": result.result_sha256, "status": item.status,
               "cutoff": cutoff.isoformat(), "metrics": item.metrics,
               "warnings": item.warnings, "errors": item.errors,
               "decision_authority": False, "execution_allowed": False}
    if item.status != "WARN":
        print("PUBLIC_MARKET_CONTROL " + json.dumps(summary, ensure_ascii=False, sort_keys=True))
        raise SystemExit("no usable real observation")
    artifact = item.artifacts[0]
    raw = (out / artifact.path).read_bytes()
    payload = json.loads(raw)
    assert hashlib.sha256(raw).hexdigest() == artifact.sha256
    assert payload["symbol"] == "600519" and payload["adjust"] == ""
    assert payload["end"] == cutoff.isoformat()
    assert payload["bars"] and all(row["date"][:10] <= cutoff.isoformat() for row in payload["bars"])
    assert payload["pit_safe"] is False and payload["historical_vintage_verified"] is False
    assert payload["source_independence_verified"] is False
    assert payload["volume_units_crosschecked"] is False
    assert payload["primary_upstream"] != "tencent"
    # This run checks the newly integrated two-vendor path, not just a
    # standalone adapter experiment. Failure to observe both remains failure.
    assert payload["crosscheck"]["status"] == "MATCH_OBSERVED_ROWS"
    observed_sources = {p["upstream"] for p in payload["providers"] if p["status"] == "OBSERVED"}
    assert "tencent" in observed_sources and len(observed_sources) == 2
    assert next(p for p in payload["providers"] if p["upstream"] == "tencent")["raw_body_parent_rehash"] == "MATCH"
    summary.update({"artifact_sha256": artifact.sha256, "local_artifact_rehash": "MATCH",
                    "providers": payload["providers"], "crosscheck": payload["crosscheck"],
                    "historical_vintage_verified": False, "raw_provider_bytes_retained": False})
    print("PUBLIC_MARKET_CONTROL " + json.dumps(summary, ensure_ascii=False, sort_keys=True))
