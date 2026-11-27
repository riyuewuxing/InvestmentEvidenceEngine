import json
from hashlib import sha256

import pytest

from investment_evidence_engine.contracts import ArtifactRef, ExecutionOperation
from investment_evidence_engine.dispatch import run_operation
from investment_evidence_engine.workers import WorkerContext


def retain_dependency(ctx, dep):
    raw = json.dumps(ctx.payloads[dep], allow_nan=False).encode()
    path = ctx.output_dir / f"{dep}.json"
    path.write_bytes(raw)
    ref = ArtifactRef(path=path.name, sha256=sha256(raw).hexdigest(),
                      size_bytes=len(raw), media_type="application/json")
    ctx.completed_operations[dep]["artifact_refs"] = [ref.model_dump(mode="json")]
    return ref


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


@pytest.mark.parametrize("kind", ["FACTOR_COMPUTE", "BACKTEST"])
@pytest.mark.parametrize("mode", ["two_series", "missing", "blocked", "wrong_symbol", "missing_identity"])
def test_compute_never_splices_or_silently_drops_declared_sources(tmp_path, kind, mode):
    ctx = WorkerContext(output_dir=tmp_path, request_as_of="2026-01-04")
    for i, symbol in enumerate(("600519", "000001"), 1):
        dep = f"market-{i}"
        ctx.payloads[dep] = {"symbol": symbol, "bars": [
            {"date": f"2026-01-0{i}", "close": 10 * i, "return": .01, "weight": 1}]}
        ctx.completed_operations[dep] = {"kind": "MARKET_DATA", "status": "WARN"}
    for dep in ("market-1", "market-2"):
        retain_dependency(ctx, dep)
    deps = ["market-1"]
    subject = "600519"
    if mode == "two_series":
        deps.append("market-2")
    elif mode == "missing":
        del ctx.payloads["market-1"]
    elif mode == "blocked":
        ctx.completed_operations["market-1"]["status"] = "BLOCK"
    elif mode == "wrong_symbol":
        subject = "000001"
    else:
        del ctx.payloads["market-1"]["symbol"]
        retain_dependency(ctx, "market-1")
    op = ExecutionOperation(operation_id="compute", kind=kind, parameters={
        "depends_on_operation_ids": deps, "subject_ids": [subject],
        "factor_spec": {"field": "close", "transform": "ROLLING_RETURN", "window": 1},
        "cost_bps": 10})
    result = run_operation(op, ctx)
    assert result.status == "BLOCK" and not result.artifacts
    assert "compute" not in ctx.payloads


def test_factor_preserves_market_envelope_identity(tmp_path):
    ctx = WorkerContext(output_dir=tmp_path, request_as_of="2026-01-04")
    ctx.payloads["market"] = {"symbol": "600519", "bars": [
        {"date": "2026-01-01", "close": 10}, {"date": "2026-01-02", "close": 11}]}
    ctx.completed_operations["market"] = {"kind": "MARKET_DATA", "status": "WARN"}
    ref = retain_dependency(ctx, "market")
    op = ExecutionOperation(operation_id="factor", kind="FACTOR_COMPUTE", parameters={
        "depends_on_operation_ids": ["market"], "subject_ids": ["600519"],
        "factor_spec": {"field": "close", "transform": "ROLLING_RETURN", "window": 1}})
    result = run_operation(op, ctx)
    assert result.status == "PASS"
    assert [r["symbol"] for r in ctx.payloads["factor"]["records"]] == ["600519", "600519"]
    assert ctx.payloads["factor"]["records"][-1]["factor_value"] == pytest.approx(.1)
    assert ctx.payloads["factor"]["compute_input_scope"]["artifact_sha256"] == ref.sha256


@pytest.mark.parametrize("kind", ["FACTOR_COMPUTE", "BACKTEST"])
@pytest.mark.parametrize("mode,reason", [
    ("two_tables", "COMPUTE_DEPENDENCY_COLLECTION_AMBIGUOUS_OR_MISSING"),
    ("empty_shadow", "COMPUTE_DEPENDENCY_COLLECTION_AMBIGUOUS_OR_MISSING"),
    ("metrics_only", "COMPUTE_DEPENDENCY_COLLECTION_AMBIGUOUS_OR_MISSING"),
    ("invalid_rows", "COMPUTE_DEPENDENCY_RECORDS_INVALID"),
    ("missing_ref", "COMPUTE_DEPENDENCY_ARTIFACT_REQUIRED"),
    ("changed_bytes", "COMPUTE_DEPENDENCY_ARTIFACT_UNVERIFIED"),
    ("context_changed", "COMPUTE_DEPENDENCY_CONTEXT_MISMATCH"),
    ("bool_number_alias", "COMPUTE_DEPENDENCY_CONTEXT_MISMATCH"),
    ("wrong_market_table", "COMPUTE_MARKET_COLLECTION_MISMATCH"),
])
def test_compute_explicit_record_and_observed_byte_binding(tmp_path, kind, mode, reason):
    ctx = WorkerContext(output_dir=tmp_path, request_as_of="2026-01-04")
    rows = [{"date": "2026-01-01", "close": 10, "return": 0, "weight": 1},
            {"date": "2026-01-02", "close": 11, "return": .1, "weight": 1}]
    payload = {"symbol": "600519", "bars": rows}
    if mode == "two_tables":
        payload["rows"] = rows
    elif mode == "empty_shadow":
        payload["records"] = []
    elif mode == "metrics_only":
        payload = {"symbol": "600519", "metrics": {"records": rows}}
    elif mode == "invalid_rows":
        payload["bars"] = [None]
    elif mode == "wrong_market_table":
        payload["records"] = payload.pop("bars")
    ctx.payloads["source"] = payload
    ctx.completed_operations["source"] = {"kind": "MARKET_DATA", "status": "WARN"}
    ref = retain_dependency(ctx, "source")
    if mode == "missing_ref":
        del ctx.completed_operations["source"]["artifact_refs"]
    elif mode == "changed_bytes":
        (tmp_path / ref.path).write_text("{}", encoding="utf-8")
    elif mode == "context_changed":
        rows[0]["close"] = 12
    elif mode == "bool_number_alias":
        rows[0]["weight"] = True
    op = ExecutionOperation(operation_id="compute", kind=kind, parameters={
        "depends_on_operation_ids": ["source"], "subject_ids": ["600519"],
        "factor_spec": {"field": "close", "transform": "ROLLING_RETURN", "window": 1},
        "cost_bps": 10})
    result = run_operation(op, ctx)
    assert result.status == "BLOCK" and result.errors == [reason]
    assert not result.artifacts and "compute" not in ctx.payloads
