import json

import pytest

from investment_evidence_engine.contracts import ExecutionOperation
from investment_evidence_engine.dispatch import run_operation
from investment_evidence_engine.workers import WorkerContext


def run(tmp_path, kind, records, **params):
    ctx = WorkerContext(output_dir=tmp_path)
    result = run_operation(ExecutionOperation(operation_id="compute", kind=kind,
        parameters={"inline_records": records, **params}), ctx)
    return result, ctx.payloads.get("compute")


@pytest.mark.parametrize("rows", [
    [{"return": None, "weight": 1}],
    [{"return": 0.01}],
    [{"return": 0.01, "weight": None}],
    [{"return": True, "weight": 0}],
    [{"return": 0.01, "weight": -0.1}],
    [{"return": 0.01, "weight": 1.1}],
    [{"return": -1.1, "weight": 1}],
    [{"return": "0.01", "weight": 1}],
    [{"return": 0.01, "weight": 1, "asset": "A"},
     {"return": 0.01, "weight": 1, "asset": "B"}],
])
def test_backtest_no_silent_defaults(tmp_path, rows):
    result, payload = run(tmp_path, "BACKTEST", rows, cost_bps=10)
    assert result.status == "BLOCK"
    assert payload is None


@pytest.mark.parametrize("cost", [None, -1, True, "10", 10000])
def test_explicit_valid_cost_required(tmp_path, cost):
    result, _ = run(tmp_path, "BACKTEST", [{"return": 0.01, "weight": 1}], cost_bps=cost)
    assert result.status == "BLOCK"


def test_first_fee_drawdown_and_no_default_annualization(tmp_path):
    result, payload = run(tmp_path, "BACKTEST", [{"return": 0, "weight": 1}], cost_bps=10)
    assert result.status == "PASS"
    assert result.metrics["max_drawdown"] == pytest.approx(-.001)
    assert result.metrics["annualized_return"] is None
    assert not payload["pit_safe"] and not payload["assumptions"]["actual_costs_verified"]


@pytest.mark.parametrize("days", [
    ["2026-01-02", "2026-01-01"], ["2026-01-01", "2026-01-01"],
    ["2026-01-01", "2026-01-02T12:00:00+08:00"],
    ["2026-01-01T12:00:00", "2026-01-02T12:00:00"],
])
def test_bad_time_order_or_precision(tmp_path, days):
    result, _ = run(tmp_path, "BACKTEST", [{"date": day, "return": 0.01, "weight": 1}
                                         for day in days], cost_bps=10)
    assert result.status == "BLOCK"


def test_pct_change_does_not_fill_missing_observation(tmp_path):
    records = [{"date": f"2026-01-0{i}", "close": v}
               for i, v in enumerate([10, None, 12, 15], 1)]
    result, payload = run(tmp_path, "FACTOR_COMPUTE", records,
                          factor_spec={"field": "close", "transform": "PCT_CHANGE"})
    assert result.status == "PASS"
    assert [row["factor_value"] for row in payload["records"]] == [None, None, None, .25]
    assert payload["undefined_output_count"] == 3
    assert not payload["missing_values_filled"]


def test_undefined_factor_not_infinite_or_zero(tmp_path):
    records = [{"date": "2026-01-01", "close": 0}, {"date": "2026-01-02", "close": 1}]
    result, _ = run(tmp_path, "FACTOR_COMPUTE", records,
                    factor_spec={"field": "close", "transform": "PCT_CHANGE"})
    assert result.status == "BLOCK"


def test_temporal_factor_rejects_missing_order_or_overwrite(tmp_path):
    records = [{"close": 10}, {"close": 12}]
    result, _ = run(tmp_path, "FACTOR_COMPUTE", records,
                    factor_spec={"field": "close", "transform": "ROLLING_RETURN", "window": 1})
    assert result.status == "BLOCK"
    result, _ = run(tmp_path, "FACTOR_COMPUTE", records,
                    factor_spec={"field": "close", "output_field": "close"})
    assert result.status == "BLOCK"


def test_factor_and_backtest_reject_input_shadowing(tmp_path):
    for kind in ("FACTOR_COMPUTE", "BACKTEST"):
        result, _ = run(tmp_path, kind, [], depends_on_operation_ids=["upstream"])
        assert result.errors == ["COMPUTE_DEPENDENCY_INLINE_CONFLICT"]


def test_explicit_annualization_is_assumed_not_certified(tmp_path):
    result, payload = run(tmp_path, "BACKTEST",
                          [{"date": "2026-01-01", "return": 0, "weight": 1},
                           {"date": "2026-01-02", "return": .1, "weight": 0}],
                          cost_bps=10, periods_per_year=252)
    assert result.status == "PASS"
    assert payload["time_label_order_verified"]
    assert result.metrics["total_return"] == pytest.approx(.999 * 1.099 - 1)
    assert not payload["assumptions"]["annualization_cadence_verified"]
    json.dumps(payload, allow_nan=False)
