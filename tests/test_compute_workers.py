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
    assert context.payloads["scan"]["input_mode"] == "INLINE_SYNTHETIC"
    assert context.payloads["scan"]["input_mode"] in result.metrics.values()


def test_inline_scan_rejects_advice_semantics_instead_of_ignoring_them(tmp_path: Path) -> None:
    operation = ExecutionOperation(
        operation_id="scan-advice-label",
        kind="OPPORTUNITY_SCAN",
        parameters={
            "inline_records": [{"asset": "A", "momentum": 0.2}],
            "rules": [{"field": "momentum", "operator": "GE", "threshold": 0}],
            "ranking_semantics": "RETURN_FORECAST",
        },
    )

    result = run_operation(operation, _context(tmp_path))

    assert result.status == "BLOCK"
    assert result.errors == ["OPPORTUNITY_SCAN_SEMANTICS_INVALID"]


def test_opportunity_scan_preserves_explicit_zero_rule_weight(tmp_path: Path) -> None:
    operation = ExecutionOperation(
        operation_id="scan-zero-weight",
        kind="OPPORTUNITY_SCAN",
        parameters={
            "inline_records": [{"asset": "A", "momentum": 0.2}],
            "rules": [{"field": "momentum", "operator": "GE", "threshold": 0, "weight": 0}],
        },
    )
    context = _context(tmp_path)

    result = run_operation(operation, context)

    assert result.status == "PASS"
    assert context.payloads["scan-zero-weight"]["rules"][0]["weight"] == 0.0
    assert context.payloads["scan-zero-weight"]["candidates"][0]["research_priority_score"] == 0.0


def test_opportunity_scan_defaults_missing_rule_weight_to_one(tmp_path: Path) -> None:
    operation = ExecutionOperation(
        operation_id="scan-default-weight",
        kind="OPPORTUNITY_SCAN",
        parameters={
            "inline_records": [{"asset": "A", "momentum": 0.2}],
            "rules": [{"field": "momentum", "operator": "GE", "threshold": 0}],
        },
    )
    context = _context(tmp_path)

    result = run_operation(operation, context)

    assert result.status == "PASS"
    assert context.payloads["scan-default-weight"]["rules"][0]["weight"] == 1.0
    assert context.payloads["scan-default-weight"]["candidates"][0]["research_priority_score"] == 1.0


@pytest.mark.parametrize(
    "parameters",
    [
        {"inline_records": [{"asset": "A", "momentum": 0.2}], "rules": []},
        {"inline_records": [{"asset": "A", "momentum": 0.2}], "rules": [{}]},
        {
            "inline_records": [{"asset": "A", "momentum": 0.2}],
            "rules": [{"field": "momentum", "operator": "GE", "threshold": 0, "extra": 1}],
        },
        {
            "inline_records": [{"asset": "A", "momentum": 0.2}],
            "rules": [{"field": "momentum", "operator": "GE"}],
        },
        {
            "inline_records": [{"asset": "A", "momentum": 0.2}],
            "rules": [{"field": "momentum", "operator": "GE", "threshold": True}],
        },
        {
            "inline_records": [{"asset": "A", "momentum": 0.2}],
            "rules": [{"field": "momentum", "operator": "GE", "threshold": float("inf")}],
        },
        {
            "inline_records": [{"asset": "A", "momentum": 0.2}],
            "rules": [{"field": "momentum", "operator": "GE", "threshold": 0, "weight": True}],
        },
        {
            "inline_records": [{"asset": "A", "momentum": 0.2}],
            "rules": [{"field": "momentum", "operator": "GE", "threshold": 0, "weight": -1}],
        },
        {
            "inline_records": [{"asset": "A", "momentum": 0.2}],
            "rules": [{"field": "momentum", "operator": "GE", "threshold": 0, "weight": float("inf")}],
        },
        {
            "inline_records": [{"asset": "A", "momentum": 0.2}],
            "rules": [{"field": "momentum", "operator": "GE", "threshold": 0}],
            "top_n": True,
        },
        {
            "inline_records": [{"asset": "A", "momentum": 0.2}],
            "rules": [{"field": "momentum", "operator": "GE", "threshold": 0}],
            "top_n": 0,
        },
        {
            "inline_records": [{"asset": "A", "momentum": 0.2}],
            "rules": [{"field": "momentum", "operator": "GE", "threshold": 0}],
            "top_n": 1001,
        },
    ],
)
def test_opportunity_scan_rejects_invalid_rule_or_top_n(parameters, tmp_path: Path) -> None:
    operation = ExecutionOperation(
        operation_id="scan-invalid",
        kind="OPPORTUNITY_SCAN",
        parameters=parameters,
    )

    result = run_operation(operation, _context(tmp_path))

    assert result.status == "BLOCK"
    assert result.errors[0].startswith("OPPORTUNITY_SCAN_")


def test_opportunity_scan_rejects_more_than_32_rules(tmp_path: Path) -> None:
    operation = ExecutionOperation(
        operation_id="scan-too-many-rules",
        kind="OPPORTUNITY_SCAN",
        parameters={
            "inline_records": [{"asset": "A", "momentum": 0.2}],
            "rules": [
                {"field": "momentum", "operator": "GE", "threshold": 0}
                for _ in range(33)
            ],
        },
    )

    result = run_operation(operation, _context(tmp_path))

    assert result.status == "BLOCK"
    assert result.errors == ["OPPORTUNITY_SCAN_RULE_COUNT_INVALID"]


def test_opportunity_scan_requires_numeric_rule_field(tmp_path: Path) -> None:
    operation = ExecutionOperation(
        operation_id="scan-nonnumeric-field",
        kind="OPPORTUNITY_SCAN",
        parameters={
            "inline_records": [{"asset": "A", "momentum": 0.2}],
            "rules": [{"field": "asset", "operator": "GE", "threshold": 0}],
        },
    )

    result = run_operation(operation, _context(tmp_path))

    assert result.status == "BLOCK"
    assert result.errors == ["OPPORTUNITY_SCAN_RULE_FIELD_NOT_NUMERIC:asset"]


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
