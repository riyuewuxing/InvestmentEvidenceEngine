"""Actual public price-to-chart chain; no raw vendor rows or image payload in logs."""
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from investment_evidence_engine.contracts import ExecutionOperation, ExecutionRequest, canonical_sha256
from investment_evidence_engine.runner import execute_request

REPO = "riyuewuxing/InvestmentEvidenceEngine"
AS_OF = "2026-11-26T14:00:00+08:00"
SUBJECT = "600519"


def main():
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    sha = os.environ["GITHUB_SHA"]
    scope = {"subject_ids": [SUBJECT], "as_of": AS_OF}
    ops = [
        ExecutionOperation(operation_id="market", kind="MARKET_DATA",
                           parameters=scope | {"history_days": 90, "adjust": ""}),
        ExecutionOperation(operation_id="price", kind="PRICE_ANALYTICS",
                           parameters=scope | {"depends_on_operation_ids": ["market"], "adjust": ""}),
        ExecutionOperation(operation_id="chart", kind="KLINE_RENDER",
                           parameters=scope | {"depends_on_operation_ids": ["market"], "adjust": ""}),
    ]
    req = ExecutionRequest(job_id="public-price-chain-control", trace_id="price-chain-20261126",
                           subject_repo=REPO, subject_commit=sha, as_of=AS_OF, operations=ops)
    req.request_sha256 = req.compute_hash()
    with TemporaryDirectory() as folder:
        root = Path(folder)
        path = root / "request.json"
        path.write_text(req.model_dump_json(), encoding="utf-8")
        out = root / "out"
        result = execute_request(path, output_dir=out, executor_repo=REPO, executor_commit=sha)
        assert result.compute_hash() == result.result_sha256 and result.request_sha256 == req.request_sha256
        report = {"status": result.status, "executor_commit": sha, "request_sha256": req.request_sha256,
                  "result_sha256": result.result_sha256, "as_of": AS_OF, "subject": SUBJECT,
                  "operations": [{"id": o.operation_id, "status": o.status,
                                  "errors": o.errors, "warnings": o.warnings} for o in result.operations],
                  "historical_vintage_verified": False, "pit_safe": False,
                  "decision_authority": False, "execution_allowed": False}
        if result.status == "WARN" and all(o.status in {"PASS", "WARN"} for o in result.operations):
            observed = {}
            for op in result.operations:
                for art in op.artifacts:
                    raw = (out / art.path).read_bytes()
                    assert len(raw) == art.size_bytes and hashlib.sha256(raw).hexdigest() == art.sha256
                    observed[art.path] = {"sha256": art.sha256, "bytes": len(raw)}
            market = json.loads((out / "market.json").read_bytes())
            price = json.loads((out / "price.json").read_bytes())
            chart = json.loads((out / "chart.json").read_bytes())
            bars = market["bars"]
            digest = canonical_sha256(bars)
            assert market["symbol"] == price["symbol"] == chart["symbol"] == SUBJECT
            assert market["as_of"] == price["as_of"] == chart["as_of"] == AS_OF
            assert market["end"] == "2026-11-25"
            assert price["price_input"]["input_bars_sha256"] == chart["price_input"]["input_bars_sha256"] == digest
            assert price["metrics"]["close"] == bars[-1]["close"]
            assert price["metrics"]["rows"] == len(bars)
            assert chart["last_rendered_date"] == price["metrics"]["last_date"] == bars[-1]["date"][:10]
            assert chart["last_rendered_date"] <= market["end"]
            assert chart["rows_rendered"] == min(260, len(bars))
            with Image.open(out / "chart.png") as im:
                size = im.size
                assert im.format == "PNG" and size[0] >= 200 and size[1] >= 200
                im.verify()
            report |= {"actual_rows": len(bars), "last_date": price["metrics"]["last_date"],
                       "close": price["metrics"]["close"], "return_20d": price["metrics"]["return_20d"],
                       "crosscheck": market["crosscheck"], "input_bars_sha256": digest,
                       "artifact_parent_rehash": "MATCH", "artifacts": observed,
                       "chart_dimensions": size, "renderer": chart["renderer"],
                       "all_three_identity_cutoff_input_match": True}
        print("PUBLIC_PRICE_CHAIN_CONTROL " + json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
        return 0 if report.get("all_three_identity_cutoff_input_match") else 2


if __name__ == "__main__":
    raise SystemExit(main())
