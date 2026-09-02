from __future__ import annotations

import argparse
import json
import os
import resource
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from investment_evidence_engine.contracts import ExecutionOperation, ExecutionRequest
from investment_evidence_engine.runner import execute_request


def _series_records(rows: int, seed: int) -> list[dict[str, object]]:
    rng = np.random.default_rng(seed)
    market_return = rng.normal(0.00025, 0.012, size=rows)
    signal = np.cumsum(rng.normal(0.0, 1.0, size=rows))
    weights = np.tanh(signal / max(float(np.std(signal)), 1e-9))
    return [
        {
            "row_id": i,
            "signal": float(signal[i]),
            "return": float(market_return[i]),
            "weight": float(weights[i]),
        }
        for i in range(rows)
    ]


def _universe_records(
    universe: int,
    seed: int,
    shard_index: int,
    shard_count: int,
) -> list[dict[str, object]]:
    rng = np.random.default_rng(seed)
    records: list[dict[str, object]] = []
    for i in range(universe):
        momentum = float(rng.normal(0.08, 0.25))
        roe = float(rng.normal(0.11, 0.07))
        valuation = float(rng.uniform(0.0, 1.0))
        liquidity = float(rng.uniform(0.0, 1.0))
        if i % shard_count != shard_index:
            continue
        records.append(
            {
                "asset_id": f"A{i:06d}",
                "momentum_120d": momentum,
                "roe": roe,
                "valuation_percentile": valuation,
                "liquidity_score": liquidity,
            }
        )
    return records


def build_request(
    *,
    rows: int,
    universe: int,
    shard_index: int,
    shard_count: int,
    subject_commit: str,
) -> ExecutionRequest:
    seed = 20260902
    series = _series_records(rows, seed)
    scan_records = _universe_records(universe, seed + 1, shard_index, shard_count)
    request = ExecutionRequest(
        job_id=f"e6-benchmark-r{rows}-u{universe}-s{shard_index}of{shard_count}",
        trace_id=f"e6-benchmark-r{rows}-u{universe}-s{shard_index}of{shard_count}",
        subject_repo="riyuewuxing/InvestmentEvidenceEngine",
        subject_commit=subject_commit,
        as_of="2026-09-02",
        generated_at=datetime.now(UTC),
        operations=[
            ExecutionOperation(
                operation_id="factor",
                kind="FACTOR_COMPUTE",
                parameters={
                    "inline_records": series,
                    "factor_spec": {
                        "factor_id": "synthetic_signal_z",
                        "field": "signal",
                        "transform": "Z_SCORE",
                        "output_field": "factor_value",
                    },
                },
            ),
            ExecutionOperation(
                operation_id="backtest",
                kind="BACKTEST",
                parameters={
                    "depends_on_operation_ids": ["factor"],
                    "return_field": "return",
                    "weight_field": "weight",
                    "cost_bps": 10,
                    "periods_per_year": 252,
                },
            ),
            ExecutionOperation(
                operation_id="scan",
                kind="OPPORTUNITY_SCAN",
                parameters={
                    "inline_records": scan_records,
                    "rules": [
                        {
                            "field": "momentum_120d",
                            "operator": "GE",
                            "threshold": 0.10,
                            "weight": 1.0,
                        },
                        {
                            "field": "roe",
                            "operator": "GE",
                            "threshold": 0.12,
                            "weight": 1.0,
                        },
                        {
                            "field": "valuation_percentile",
                            "operator": "LE",
                            "threshold": 0.40,
                            "weight": 1.0,
                        },
                        {
                            "field": "liquidity_score",
                            "operator": "GE",
                            "threshold": 0.30,
                            "weight": 0.5,
                        },
                    ],
                    "top_n": 100,
                },
            ),
        ],
    )
    request.request_sha256 = request.compute_hash()
    return request


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--universe", type=int, required=True)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, default=Path("benchmark-output"))
    args = parser.parse_args()

    if args.rows < 100 or args.universe < 100:
        raise SystemExit("benchmark sizes are too small")
    if args.shard_count < 1 or not (0 <= args.shard_index < args.shard_count):
        raise SystemExit("invalid shard configuration")

    executor_commit = os.environ.get("GITHUB_SHA") or ("0" * 40)
    executor_repo = os.environ.get("GITHUB_REPOSITORY") or "local/InvestmentEvidenceEngine"
    args.output_dir.mkdir(parents=True, exist_ok=True)

    request = build_request(
        rows=args.rows,
        universe=args.universe,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
        subject_commit=executor_commit,
    )
    request_path = args.output_dir / "benchmark_request.json"
    request_path.write_text(request.model_dump_json(indent=2), encoding="utf-8")

    start = time.perf_counter()
    result = execute_request(
        request_path,
        output_dir=args.output_dir / "run",
        executor_repo=executor_repo,
        executor_commit=executor_commit,
    )
    elapsed = time.perf_counter() - start
    max_rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    scan_rows = sum(1 for i in range(args.universe) if i % args.shard_count == args.shard_index)

    report = {
        "schema_version": 1,
        "profile": {
            "series_rows": args.rows,
            "universe_rows_total": args.universe,
            "universe_rows_in_shard": scan_rows,
            "shard_index": args.shard_index,
            "shard_count": args.shard_count,
        },
        "elapsed_seconds": elapsed,
        "max_rss_kib": max_rss_kib,
        "result_status": result.status,
        "operation_statuses": {item.operation_id: item.status for item in result.operations},
        "request_sha256": request.request_sha256,
        "result_sha256": result.result_sha256,
        "executor_repo": result.executor.repo,
        "executor_commit": result.executor.commit,
        "decision_authority": False,
    }
    report_path = args.output_dir / "benchmark_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))

    if result.status in {"BLOCK", "ERROR"}:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
