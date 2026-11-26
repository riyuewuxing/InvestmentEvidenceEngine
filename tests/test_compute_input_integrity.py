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


@pytest.mark.parametrize("kind", ["BACKTEST", "FACTOR_COMPUTE"])
@pytest.mark.parametrize("cutoff,day", [
    ("2026-01-01", "2026-01-02"),
    ("2026-01-02T10:00:00+08:00", "2026-01-02"),
    ("2026-01-02T10:00:00+08:00", "2026-01-02T10:01:00+08:00"),
])
def test_compute_cannot_include_future_or_same_day_unknown_time(tmp_path, kind, cutoff, day):
    ctx = WorkerContext(output_dir=tmp_path, request_as_of=cutoff)
    op = ExecutionOperation(operation_id="compute", kind=kind, parameters={
        "inline_records": [{"date": day, "close": 10, "return": 0, "weight": 0}],
        "factor_spec": {"field": "close", "transform": "ROLLING_RETURN", "window": 1},
        "cost_bps": 10,
    })
    result = run_operation(op, ctx)
    assert result.status == "BLOCK"
    assert result.errors == ["COMPUTE_RECORD_AFTER_OR_UNPROVEN_AT_CUTOFF"]


def test_prior_day_labels_allowed_under_precise_later_cutoff(tmp_path):
    ctx = WorkerContext(output_dir=tmp_path, request_as_of="2026-01-03T10:00:00+08:00")
    op = ExecutionOperation(operation_id="compute", kind="BACKTEST", parameters={
        "inline_records": [{"date": "2026-01-01", "return": 0, "weight": 1},
                           {"date": "2026-01-02", "return": .01, "weight": 0}],
        "cost_bps": 10})
    result = run_operation(op, ctx)
    assert result.status == "PASS"
    assert ctx.payloads["compute"]["time_label_order_verified"]
    assert not ctx.payloads["compute"]["pit_safe"]


@pytest.mark.parametrize("transform", ["IDENTITY", "RANK_PCT", "Z_SCORE"])
@pytest.mark.parametrize("cutoff, label", [
    ("2026-01-01", "2026-01-02"),
    ("2026-01-02T10:00:00+08:00", "2026-01-02"),
    ("2026-01-02T10:00:00+08:00", "2026-01-02T02:01:00Z"),
])
def test_non_temporal_factor_respects_sealed_cutoff(tmp_path, transform, cutoff, label):
    ctx = WorkerContext(output_dir=tmp_path, request_as_of=cutoff)
    op = ExecutionOperation(operation_id="factor", kind="FACTOR_COMPUTE", parameters={
        "inline_records": [{"date": label, "value": 3}],
        "factor_spec": {"field": "value", "transform": transform},
    })
    result = run_operation(op, ctx)
    assert result.status == "BLOCK"
    assert result.errors == ["COMPUTE_RECORD_AFTER_OR_UNPROVEN_AT_CUTOFF"]
    assert "factor" not in ctx.payloads


@pytest.mark.parametrize("transform", ["RANK_PCT", "Z_SCORE"])
def test_rank_or_zscore_cannot_normalize_across_time(tmp_path, transform):
    result, payload = run(tmp_path, "FACTOR_COMPUTE",
                          [{"date": "2026-01-01", "value": 3},
                           {"date": "2026-01-02", "value": 6}],
                          factor_spec={"field": "value", "transform": transform})
    assert result.status == "BLOCK"
    assert result.errors == ["FACTOR_MULTI_TIME_BATCH_NORMALIZATION_FORBIDDEN"]
    assert payload is None


@pytest.mark.parametrize("transform, expected", [("RANK_PCT", [.5, 1.]), ("Z_SCORE", [-1., 1.])])
def test_cross_section_snapshot_remains_supported(tmp_path, transform, expected):
    result, payload = run(tmp_path, "FACTOR_COMPUTE",
                          [{"date": "2026-01-01", "symbol": "A", "value": 3},
                           {"date": "2026-01-01", "symbol": "B", "value": 6}],
                          as_of="2026-01-02",
                          factor_spec={"field": "value", "transform": transform})
    assert result.status == "PASS"
    assert [row["factor_value"] for row in payload["records"]] == pytest.approx(expected)
    assert payload["observation_label_scope"] == "SINGLE_DECLARED_SNAPSHOT_LABEL"
    assert payload["batch_normalization_basis"] == "WHOLE_INPUT_NOT_HISTORICAL_SIGNAL"
    assert not payload["pit_safe"]


@pytest.mark.parametrize("kind", ["FACTOR_COMPUTE", "BACKTEST"])
def test_explicit_time_field_cannot_hide_future_timestamp(tmp_path, kind):
    result, payload = run(tmp_path, kind, [
        {"date": "2026-01-01", "timestamp": "2026-01-03T10:00:00+08:00",
         "value": 3, "return": .01, "weight": 1}],
        as_of="2026-01-02", time_field="date",
        factor_spec={"field": "value", "transform": "IDENTITY"}, cost_bps=10)
    assert result.errors == ["COMPUTE_RECORD_AFTER_OR_UNPROVEN_AT_CUTOFF"]
    assert payload is None


def test_identity_allows_distinct_valid_date_labels(tmp_path):
    result, payload = run(tmp_path, "FACTOR_COMPUTE",
                          [{"date": "2026-01-01", "value": 3},
                           {"date": "2026-01-02", "value": 6}],
                          as_of="2026-01-02", factor_spec={"field": "value"})
    assert result.status == "PASS"
    assert payload["observation_label_scope"] == "DECLARED_OBSERVATION_LABELS"
    assert not payload["pit_safe"]


def test_zscore_cannot_turn_overflowed_variance_into_zeros(tmp_path):
    result, payload = run(tmp_path, "FACTOR_COMPUTE",
                          [{"value": -1e200}, {"value": 1e200}],
                          factor_spec={"field": "value", "transform": "Z_SCORE"})
    assert result.errors == ["FACTOR_NORMALIZATION_NONFINITE"]
    assert payload is None
