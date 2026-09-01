from __future__ import annotations

from .contracts import ExecutionOperation, OperationResult
from .fundamental_worker import run_fundamental_with_pit_guard
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
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=[f"UNIMPLEMENTED_OPERATION:{operation.kind}"],
        )
    try:
        return worker(operation, context)
    except Exception as exc:  # noqa: BLE001 - operation boundary must return structured failure.
        return OperationResult(
            operation_id=operation.operation_id,
            status="ERROR",
            exit_code=1,
            errors=[f"{type(exc).__name__}:{exc}"],
        )
