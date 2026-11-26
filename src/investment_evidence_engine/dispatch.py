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


def run_research(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    """Report observed prerequisites without treating transport as PIT admission."""
    params = operation.parameters
    ids = params.get("input_artifact_ids")
    ref = (context.input_artifacts.get(ids[0]) if isinstance(ids, list) and len(ids) == 1
           and isinstance(ids[0], str) else None)
    cutoff = params.get("as_of")
    attachment_scope = bool(ref is not None and isinstance(cutoff, str)
                            and ref.as_of == cutoff == context.request_as_of)
    deps = params.get("depends_on_operation_ids")
    dep = deps[0] if isinstance(deps, list) and len(deps) == 1 and isinstance(deps[0], str) else None
    provenance = context.completed_operations.get(dep, {}) if dep else {}
    payload = context.payloads.get(dep, {}) if dep else {}
    frame = context.frames.get(dep) if dep else None
    scoped_market = bool(attachment_scope and provenance.get("kind") == "MARKET_DATA"
                         and provenance.get("status") in {"PASS", "WARN"}
                         and provenance.get("as_of") == cutoff
                         and payload.get("as_of") == cutoff and payload.get("symbol") == ref.selector.value
                         and frame is not None and not frame.empty)
    # The context's attachment references are installed only after the runner
    # observes the actual attachment. They are not independent source lineage.
    readiness = {
        "candidate_attachment": "CONTEXT_SCOPE_MATCH_TRANSPORT_ONLY" if attachment_scope else "UNVERIFIED",
        "market_input": "OBSERVED_SCOPE_MATCH_ONLY" if scoped_market else "UNVERIFIED",
        "profile_requested": params.get("profile") == "SINGLE_ASSET_MOMENTUM_V1",
        "historical_source_vintage": "NOT_ADMITTED",
        "historical_listing_and_corporate_actions": "NOT_ADMITTED",
        "historical_execution_and_costs": "NOT_ADMITTED",
        "formal_profile": "NOT_ADMITTED",
        "private_source_graph": "NOT_VERIFIED_BY_PUBLIC_ENGINE",
        "research_admitted": False,
        "pit_safe": False,
        "decision_authority": False,
        "execution_allowed": False,
    }
    return OperationResult(
        operation_id=operation.operation_id, status="BLOCK", exit_code=2,
        errors=["RESEARCH_POINT_IN_TIME_SOURCE_VINTAGE_AND_PROFILE_NOT_ADMITTED"],
        metrics={"research_readiness": readiness},
    )


EXTRA_WORKERS = {
    "RESEARCH": run_research,
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
        "as_of": raw_as_of if isinstance(raw_as_of, str) else None,
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
