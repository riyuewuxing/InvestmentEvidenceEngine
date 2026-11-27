"""One bounded public fixed-rule counterexample control per predeclared subject.

Only derived metrics and byte witnesses are logged; original market bytes are temporary.
Do not replace the existing prospective study or use this as formal admission.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from investment_evidence_engine.contracts import ExecutionOperation, ExecutionRequest
from investment_evidence_engine.research_falsification import (
    CONTROL_AS_OF,
    CONTROL_END,
    CONTROL_START,
    CONTROL_SYMBOLS,
    CRITERION,
    assess_test_segment,
)
from investment_evidence_engine.research_profile_evidence import evaluate_market_profile
from investment_evidence_engine.runner import execute_request
from investment_evidence_engine.snapshot_integrity import strict_json_loads
from investment_evidence_engine.transport_integrity import read_verified_artifact

REPO = "riyuewuxing/InvestmentEvidenceEngine"


def verify_factor(raw_market: bytes, raw_factor: bytes, market_sha: str, symbol: str) -> dict:
    market = strict_json_loads(raw_market)
    factor = strict_json_loads(raw_factor)
    scope = factor.get("compute_input_scope", {})
    if (scope.get("artifact_sha256") != market_sha or scope.get("artifact_rehash") != "MATCH"
            or scope.get("operation_id") != "market" or scope.get("record_collection") != "bars"
            or scope.get("artifact_size_bytes") != len(raw_market)
            or factor.get("pit_safe") is not False or factor.get("decision_authority") is not False):
        raise ValueError("FALSIFICATION_FACTOR_LINEAGE")
    bars, records = market["bars"], factor["records"]
    if len(bars) != len(records) or scope.get("record_count") != len(bars):
        raise ValueError("FALSIFICATION_FACTOR_RECORD_COUNT")
    max_error = 0.0
    for i, (bar, row) in enumerate(zip(bars, records, strict=True)):
        if row.get("date") != bar["date"] or row.get("symbol") != symbol:
            raise ValueError("FALSIFICATION_FACTOR_RECORD_IDENTITY")
        value = row.get("rolling_return_20")
        if i < 20:
            if value is not None:
                raise ValueError("FALSIFICATION_FACTOR_WARMUP")
        else:
            expected = bar["close"] / bars[i - 20]["close"] - 1
            if type(value) not in {int, float} or not math.isfinite(value) or abs(value-expected) > 1e-9:
                raise ValueError("FALSIFICATION_FACTOR_RECOMPUTE")
            max_error = max(max_error, abs(value-expected))
    return {"record_count": len(bars), "warmup_nulls": 20, "formula_recompute": "MATCH",
            "max_absolute_serialization_error": max_error,
            "factor_dependency_artifact": scope, "signal_lag_not_claimed_for_factor": True}


def main(symbol: str) -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO or symbol not in CONTROL_SYMBOLS:
        raise SystemExit("fixed public control required")
    sha = os.environ["GITHUB_SHA"]
    history_days = (date.fromisoformat(CONTROL_END)-date.fromisoformat(CONTROL_START)).days
    report = {"status": "BLOCK", "symbol": symbol, "executor_commit": sha,
              "predeclared_subjects": list(CONTROL_SYMBOLS), "as_of": CONTROL_AS_OF,
              "start": CONTROL_START, "end": CONTROL_END, "criterion": CRITERION,
              "raw_body_retained": False, "formal_profile_admitted": False,
              "historical_vintage_verified": False, "pit_safe": False,
              "decision_authority": False, "execution_allowed": False}
    operations = [
        ExecutionOperation(operation_id="market", kind="MARKET_DATA",
            parameters={"as_of": CONTROL_AS_OF, "subject_ids": [symbol],
                        "history_days": history_days, "history_end_offset_days": 1,
                        "adjust": "", "price_tolerance": 0.001},
            expected_outputs=["market.json"], evidence_domains=["MARKET"]),
        ExecutionOperation(operation_id="factor", kind="FACTOR_COMPUTE",
            parameters={"as_of": CONTROL_AS_OF, "subject_ids": [symbol],
                        "depends_on_operation_ids": ["market"],
                        "factor_spec": {"field": "close", "transform": "ROLLING_RETURN",
                                        "window": 20, "output_field": "rolling_return_20"}},
            expected_outputs=["factor.json"], evidence_domains=["PRICE_STRUCTURE"]),
    ]
    req = ExecutionRequest(job_id=f"public-falsification-{symbol}",
        trace_id=f"public-falsification-20261127-{symbol}", subject_repo=REPO,
        subject_commit=sha, as_of=CONTROL_AS_OF, operations=operations)
    req.request_sha256 = req.compute_hash()
    with TemporaryDirectory() as temp:
        root = Path(temp)
        path = root / "request.json"
        path.write_text(req.model_dump_json(), encoding="utf-8")
        out = root / "out"
        try:
            res = execute_request(path, output_dir=out, executor_repo=REPO, executor_commit=sha)
            report |= {"request_sha256": req.request_sha256, "result_sha256": res.result_sha256,
                       "operations": [{"id": op.operation_id, "status": op.status, "errors": op.errors,
                                       "metrics": op.metrics} for op in res.operations]}
            if res.result_sha256 != res.compute_hash() or res.status not in {"PASS", "WARN"}:
                raise ValueError("FALSIFICATION_SEALED_CHAIN_BLOCK")
            if len(res.operations) != 2 or any(len(op.artifacts) != 1 for op in res.operations):
                raise ValueError("FALSIFICATION_ARTIFACT_CHAIN")
            ma, fa = [op.artifacts[0] for op in res.operations]
            raw = read_verified_artifact(out, ma.path, ma.sha256, ma.size_bytes)
            factor = read_verified_artifact(out, fa.path, fa.sha256, fa.size_bytes)
            payload = strict_json_loads(raw)
            if (payload.get("start"), payload.get("end")) != (CONTROL_START, CONTROL_END):
                raise ValueError("FALSIFICATION_FIXED_WINDOW")
            profile = evaluate_market_profile(raw, symbol=symbol, as_of=CONTROL_AS_OF)
            report |= {"market_artifact_sha256": ma.sha256, "factor_artifact_sha256": fa.sha256,
                       "market_and_factor_rehash": "MATCH", "providers": payload["providers"],
                       "crosscheck": payload["crosscheck"],
                       "factor_binding": verify_factor(raw, factor, ma.sha256, symbol),
                       "profile_receipt": profile,
                       "falsification": assess_test_segment(profile["raw_price_diagnostic"]),
                       "status": "WARN"}
        except (ValueError, TypeError, KeyError, OSError, RuntimeError, OverflowError) as exc:
            reason = str(exc)
            report["blocker"] = reason if reason.startswith(("FALSIFICATION_", "RESEARCH_")) else type(exc).__name__
    print("PUBLIC_FIXED_RESEARCH_FALSIFICATION " + json.dumps(report, ensure_ascii=False,
          sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", choices=CONTROL_SYMBOLS, required=True)
    raise SystemExit(main(parser.parse_args().symbol))
