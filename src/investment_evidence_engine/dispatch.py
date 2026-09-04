from __future__ import annotations

from .contracts import ExecutionOperation, OperationResult
from .fundamental_worker import run_fundamental_with_pit_guard
from .market_universe_worker import run_market_universe
from .market_worker import run_market_data_resilient
from .official_worker import run_official_source_resilient
from .research_compute import (
    run_backtest,
    run_factor_compute,
    run_opportunity_scan,
    run_pit_replay,
    run_test_suite,
)
from .resilient_industry_worker import run_industry_macro_resilient
from .supplemental_workers import run_ownership_flow, run_portfolio_math
from .workers import WORKERS as BASE_WORKERS
from .workers import WorkerContext

EXTRA_WORKERS = {
    "MARKET_UNIVERSE": run_market_universe,
    "MARKET_DATA": run_market_data_resilient,
    "FUNDAMENTAL_HISTORY": run_fundamental_with_pit_guard,
    "INDUSTRY_MACRO": run_industry_macro_resilient,
    "OFFICIAL_SOURCE": run_official_source_resilient,
    "OWNERSHIP_FLOW": run_ownership_flow,
    "PIT_REPLAY": run_pit_replay,
    "FACTOR_COMPUTE": run_factor_compute,
    "BACKTEST": run_backtest,
    "OPPORTUNITY_SCAN": run_opportunity_scan,
    "PORTFOLIO_MATH": run_portfolio_math,
    "TEST_SUITE": run_test_suite,
}


def run_operation(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    worker = EXTRA_WORKERS.get(operation.kind) or BASE_WORKERS.get(operation.kind)
    if worker is None:
        result = OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=[f"UNIMPLEMENTED_OPERATION:{operation.kind}"],
        )
    else:
        try:
            result = worker(operation, context)
        except Exception as exc:  # noqa: BLE001 - operation boundary must return structured failure.
            result = OperationResult(
                operation_id=operation.operation_id,
                status="ERROR",
                exit_code=1,
                errors=[f"{type(exc).__name__}:{exc}"],
            )
    raw_as_of = operation.parameters.get("as_of")
    provenance = {
        "kind": operation.kind,
        "status": result.status,
        "as_of": str(raw_as_of)[:10] if raw_as_of is not None else None,
    }
    if operation.kind == "MARKET_UNIVERSE":
        raw_market = operation.parameters.get("market")
        raw_asset_type = operation.parameters.get("asset_type")
        provenance["market"] = (
            "CN_A" if raw_market is None or not str(raw_market).strip() else str(raw_market).strip().upper()
        )
        provenance["asset_type"] = (
            "STOCK"
            if raw_asset_type is None or not str(raw_asset_type).strip()
            else str(raw_asset_type).strip().upper()
        )
    context.completed_operations[operation.operation_id] = provenance
    return result
