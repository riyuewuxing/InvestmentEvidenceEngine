from pathlib import Path

import pytest

from investment_evidence_engine.contracts import ExecutionOperation
from investment_evidence_engine.dispatch import run_operation
from investment_evidence_engine.workers import WorkerContext


def _context(tmp_path: Path) -> WorkerContext:
    return WorkerContext(output_dir=tmp_path)


def test_pit_replay_rejects_future_record(tmp_path: Path) -> None:
    operation = ExecutionOperation(
        operation_id="pit",
        kind="PIT_REPLAY",
        parameters={
            "as_of": "2026-01-10",
            "inline_records": [
                {"value": 1, "available_at": "2026-01-09"},
                {"value": 2, "available_at": "2026-01-11"},
            ],
        },
    )
    result = run_operation(operation, _context(tmp_path))
    assert result.status == "BLOCK"
    assert "FUTURE_RECORDS_REJECTED:1" in result.errors


def test_factor_compute_rank_pct(tmp_path: Path) -> None:
    operation = ExecutionOperation(
        operation_id="factor",
        kind="FACTOR_COMPUTE",
        parameters={
            "inline_records": [{"asset": "A", "roe": 10}, {"asset": "B", "roe": 20}],
            "factor_spec": {"field": "roe", "transform": "RANK_PCT", "output_field": "score"},
        },
    )
    result = run_operation(operation, _context(tmp_path))
    assert result.status == "PASS"
    assert result.metrics["count"] == 2


def test_backtest_is_lagged_and_net_of_costs(tmp_path: Path) -> None:
    operation = ExecutionOperation(
        operation_id="bt",
        kind="BACKTEST",
        parameters={
            "inline_records": [
                {"return": 0.10, "weight": 1.0},
                {"return": -0.05, "weight": 0.0},
                {"return": 0.02, "weight": 1.0},
            ],
            "cost_bps": 10,
        },
    )
    result = run_operation(operation, _context(tmp_path))
    assert result.status == "PASS"
    assert result.metrics["net_of_costs"] is True
    assert result.metrics["total_turnover"] > 0


def test_opportunity_scan_is_research_priority_only(tmp_path: Path) -> None:
    operation = ExecutionOperation(
        operation_id="scan",
        kind="OPPORTUNITY_SCAN",
        parameters={
            "inline_records": [{"asset": "A", "momentum": 0.2}, {"asset": "B", "momentum": -0.1}],
            "rules": [{"field": "momentum", "operator": "GE", "threshold": 0.0, "weight": 2.0}],
        },
    )
    context = _context(tmp_path)
    result = run_operation(operation, context)
    assert result.status == "PASS"
    assert context.payloads["scan"]["ranking_semantics"] == "RESEARCH_PRIORITY_NOT_RETURN_FORECAST"


def test_portfolio_math_rejects_private_scope(tmp_path: Path) -> None:
    operation = ExecutionOperation(
        operation_id="portfolio",
        kind="PORTFOLIO_MATH",
        parameters={
            "portfolio_scope": "real_account",
            "assets": [{"asset_id": "A", "weight": 1.0}],
        },
    )
    result = run_operation(operation, _context(tmp_path))
    assert result.status == "BLOCK"
    assert "PORTFOLIO_MATH_PRIVATE_SCOPE_FORBIDDEN" in result.errors


def test_portfolio_math_covariance(tmp_path: Path) -> None:
    operation = ExecutionOperation(
        operation_id="portfolio",
        kind="PORTFOLIO_MATH",
        parameters={
            "portfolio_scope": "synthetic",
            "assets": [
                {"asset_id": "A", "weight": 0.6, "expected_return": 0.08},
                {"asset_id": "B", "weight": 0.4, "expected_return": 0.04},
            ],
            "covariance_matrix": [[0.04, 0.01], [0.01, 0.09]],
        },
    )
    result = run_operation(operation, _context(tmp_path))
    assert result.status == "PASS"
    assert result.metrics["portfolio_volatility"] is not None
    assert result.metrics["hhi"] == 0.52


def test_test_suite_blocks_unknown_command(tmp_path: Path) -> None:
    operation = ExecutionOperation(
        operation_id="tests",
        kind="TEST_SUITE",
        parameters={"suites": ["shell"]},
    )
    result = run_operation(operation, _context(tmp_path))
    assert result.status == "BLOCK"
    assert result.errors[0].startswith("UNSAFE_OR_UNKNOWN_TEST_SUITE")


def test_pit_replay_never_promotes_publication_or_date_only(tmp_path):
    cutoff = "2026-01-10T08:30:00+08:00"
    op = ExecutionOperation(operation_id="pit",kind="PIT_REPLAY",parameters={
        "as_of":cutoff,"inline_records":[
            {"published_at":"2026-01-09T08:00:00+08:00"},
            {"available_at":"2026-01-09","retrieved_at":"2026-01-09"},
            {"available_at":"2026-01-09T08:00:00+08:00",
             "retrieved_at":"2026-01-10T09:00:00+08:00"},
        ]})
    ctx = _context(tmp_path)
    result = run_operation(op,ctx)
    assert result.status == "BLOCK"
    assert result.metrics["eligible_count"] == 0
    assert result.metrics["future_rejected_count"] == 1
    assert not result.metrics["pit_safe"]


def test_pit_replay_complete_chronology_is_only_diagnostic(tmp_path):
    op = ExecutionOperation(operation_id="pit",kind="PIT_REPLAY",parameters={
        "as_of":"2026-01-10T08:30:00+08:00","inline_records":[{
            "available_at":"2026-01-09T08:00:00+08:00",
            "retrieved_at":"2026-01-09T01:00:00Z"}]})
    ctx = _context(tmp_path)
    result = run_operation(op,ctx)
    assert result.status == "WARN"
    assert result.metrics["chronology_complete"]
    assert not result.metrics["pit_safe"]
    assert not ctx.payloads["pit"]["historical_vintage_verified"]


@pytest.mark.parametrize("cov", [[[1,2],[0,1]], [[1,2],[2,1]], [[-1,0],[0,1]],
                              [[1,True],[True,1]], [[1e-20,2e-20],[2e-20,1e-20]]])
def test_portfolio_blocks_invalid_covariance_even_if_weighted_variance_positive(tmp_path,cov):
    op = ExecutionOperation(operation_id="p",kind="PORTFOLIO_MATH",parameters={
        "assets":[{"asset_id":"A","weight":.5},{"asset_id":"B","weight":.5}],
        "covariance_matrix":cov})
    assert run_operation(op,_context(tmp_path)).status == "BLOCK"


@pytest.mark.parametrize("assets", [
    [{"asset_id":"A","weight":1},{"asset_id":"A","weight":1}],
    [{"asset_id":"A","weight":2},{"asset_id":"B","weight":-1}],
    [{"asset_id":"A"}], [{"asset_id":"A","weight":True}],
    [{"asset_id":"A","weight":1,"expected_return":float("inf")}],
])
def test_portfolio_blocks_ambiguous_or_invalid_assets(tmp_path,assets):
    op = ExecutionOperation(operation_id="p",kind="PORTFOLIO_MATH",parameters={"assets":assets})
    assert run_operation(op,_context(tmp_path)).status == "BLOCK"


def test_portfolio_component_sum_and_zero_volatility_undefined(tmp_path):
    op = ExecutionOperation(operation_id="p",kind="PORTFOLIO_MATH",parameters={
        "assets":[{"asset_id":"A","weight":.6},{"asset_id":"B","weight":.4}],
        "covariance_matrix":[[.04,.01],[.01,.09]]})
    ctx = _context(tmp_path)
    result = run_operation(op,ctx)
    payload = ctx.payloads["p"]
    assert sum(x["component_volatility_contribution"] for x in payload["risk_contributions"]) == pytest.approx(
        result.metrics["portfolio_volatility"])
    assert not payload["formal_marginal_portfolio_risk_estimated"]
    op.parameters["covariance_matrix"] = [[0,0],[0,0]]
    assert run_operation(op,ctx).metrics["portfolio_volatility"] == 0
    assert ctx.payloads["p"]["risk_contributions"] == []
    assert ctx.payloads["p"]["risk_contribution_status"] == "UNDEFINED_ZERO_VOLATILITY"
