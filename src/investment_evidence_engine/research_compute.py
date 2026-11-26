from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from datetime import date
from numbers import Real
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from .contracts import ArtifactRef, ExecutionOperation, OperationResult
from .evidence_time_guard import SHANGHAI, parse_event_stamp, source_visible, validate_event_cutoff
from .workers import WorkerContext


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _artifact(path: Path, media_type: str = "application/json") -> ArtifactRef:
    return ArtifactRef(
        path=path.name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        media_type=media_type,
        size_bytes=path.stat().st_size,
    )


def _nested_records(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
        return [dict(item) for item in payload]
    if not isinstance(payload, dict):
        return []
    for key in ("records", "bars", "rows", "data", "eligible_records"):
        value = payload.get(key)
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return [dict(item) for item in value]
    metrics = payload.get("metrics")
    if isinstance(metrics, dict):
        nested = _nested_records(metrics)
        if nested:
            return nested
    return []


def _records(operation: ExecutionOperation, context: WorkerContext) -> list[dict[str, object]]:
    inline = operation.parameters.get("inline_records")
    if isinstance(inline, list) and all(isinstance(item, dict) for item in inline):
        return [dict(item) for item in inline]
    dependencies = operation.parameters.get("depends_on_operation_ids") or []
    if isinstance(dependencies, list):
        combined: list[dict[str, object]] = []
        for dependency in dependencies:
            payload = context.payloads.get(str(dependency))
            if payload is not None:
                combined.extend(_nested_records(payload))
        if combined:
            return combined
    return []


def run_pit_replay(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    """Check stated observation chronology, never attest historical source vintage."""
    records = _records(operation, context)
    cutoff_raw = operation.parameters.get("as_of")
    cutoff, day_scope = validate_event_cutoff(cutoff_raw)
    if cutoff is None:
        raise ValueError("PIT_REPLAY requires as_of")
    # An operation may narrow, but never extend, the sealed request scope.
    if context.request_as_of is not None:
        ceiling, ceiling_day_only = validate_event_cutoff(context.request_as_of)
        if ceiling is None:
            raise ValueError("PIT_REPLAY_REQUEST_CUTOFF_REQUIRED")
        if ceiling_day_only:
            op_day = cutoff.date() if day_scope else cutoff.astimezone(SHANGHAI).date()
            outside = op_day > ceiling.date()
        elif day_scope:
            # A whole-day filter cannot prove an intraday ceiling.
            outside = True
        else:
            outside = cutoff > ceiling
        if outside:
            return OperationResult(operation_id=operation.operation_id, status="BLOCK", exit_code=2,
                                   errors=["PIT_REPLAY_REQUEST_SCOPE_EXCEEDED"])
    if ("inline_records" in operation.parameters
            and "depends_on_operation_ids" in operation.parameters):
        return OperationResult(operation_id=operation.operation_id, status="BLOCK", exit_code=2,
                               errors=["PIT_REPLAY_DEPENDENCY_INLINE_CONFLICT"])
    available_field = str(operation.parameters.get("available_at_field") or "available_at")
    published_field = str(operation.parameters.get("published_at_field") or "published_at")
    retrieved_field = str(operation.parameters.get("retrieved_at_field") or "retrieved_at")
    strict = operation.parameters.get("strict", True)
    if type(strict) is not bool or len({available_field, published_field, retrieved_field}) != 3:
        raise ValueError("PIT_REPLAY_INVALID_FIELD_OR_STRICT_SCOPE")

    eligible = []
    future = []
    missing_availability = []
    invalid_chronology = []
    for index, record in enumerate(records):
        available, _ = parse_event_stamp(record.get(available_field))
        retrieved, _ = parse_event_stamp(record.get(retrieved_field))
        published_raw = record.get(published_field)
        published, _ = parse_event_stamp(published_raw)
        # Detect explicit future evidence even when the other fields are absent.
        stamps = (available, retrieved, published)
        if day_scope:
            later = any(stamp is not None and
                (stamp.astimezone(SHANGHAI) if stamp.utcoffset() is not None else stamp).date()
                > cutoff.date() for stamp in stamps)
        else:
            later = any(stamp is not None and stamp.utcoffset() is not None
                        and stamp > cutoff for stamp in stamps)
        if later:
            future.append(index)
            continue
        if available is None or retrieved is None:
            missing_availability.append(index)
            continue
        if (day_scope or (published_raw is not None and published is None)
                or not source_visible(available_at=available, retrieved_at=retrieved,
                                      published_at=published, cutoff=cutoff)):
            invalid_chronology.append(index)
            continue
        eligible.append(record)

    blockers = []
    if day_scope:
        blockers.append("EXACT_AWARE_CUTOFF_REQUIRED")
    if future:
        blockers.append(f"FUTURE_RECORDS_REJECTED:{len(future)}")
    if missing_availability:
        blockers.append(f"MISSING_AVAILABILITY_OR_RETRIEVAL:{len(missing_availability)}")
    if invalid_chronology:
        blockers.append(f"INVALID_OR_UNVERIFIED_CHRONOLOGY:{len(invalid_chronology)}")
    if not records:
        blockers.append("NO_REPLAY_RECORDS")
    elif not eligible:
        blockers.append("NO_CHRONOLOGY_ELIGIBLE_RECORDS")
    # Even complete caller-supplied timestamps do not prove the bytes existed then.
    # The non-strict mode may expose a partial chronology diagnostic, never PIT-safe.
    status = "BLOCK" if blockers and (strict or not eligible or future) else "WARN"
    warnings = ["CALLER_STATED_CHRONOLOGY_NOT_HISTORICAL_VINTAGE_OR_ADMISSION"]
    if blockers and status == "WARN":
        warnings.extend(blockers)
    payload = {
        "as_of": cutoff_raw,
        "input_count": len(records),
        "eligible_count": len(eligible),
        "future_rejected_count": len(future),
        "missing_availability_count": len(missing_availability),
        "invalid_chronology_count": len(invalid_chronology),
        "eligible_records": eligible,
        "strict": strict,
        "chronology_complete": not blockers,
        "pit_safe": False,
        "historical_vintage_verified": False,
        "decision_authority": False,
        "warnings": warnings,
    }
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    context.payloads[operation.operation_id] = payload
    return OperationResult(
        operation_id=operation.operation_id,
        status=status,
        exit_code=2 if status == "BLOCK" else 0,
        artifacts=[_artifact(path)],
        metrics={key: payload[key] for key in (
            "input_count", "eligible_count", "future_rejected_count", "missing_availability_count",
            "invalid_chronology_count", "chronology_complete", "pit_safe"
        )},
        warnings=warnings,
        errors=blockers if status == "BLOCK" else [],
    )


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _compute_block(operation: ExecutionOperation, reason: str) -> OperationResult:
    return OperationResult(operation_id=operation.operation_id, status="BLOCK",
                           exit_code=2, errors=[reason])


def _compute_records(operation: ExecutionOperation, context: WorkerContext) -> list[dict]:
    if "inline_records" in operation.parameters and "depends_on_operation_ids" in operation.parameters:
        raise ValueError("COMPUTE_DEPENDENCY_INLINE_CONFLICT")
    return _records(operation, context)


def _chronological_rows(records: list[dict], parameters: dict, *, required: bool) -> bool:
    """Date/instant label order only, not actual availability or market calendar proof."""
    explicit = parameters.get("time_field")
    if explicit is not None and (not isinstance(explicit, str) or not explicit.strip()):
        raise ValueError("COMPUTE_TIME_FIELD_INVALID")
    field = explicit or next((k for k in ("date", "session", "timestamp")
                             if any(k in row for row in records)), None)
    # Time-series operations cannot blend two distinct security identities.
    for key in ("subject_id", "asset", "asset_id", "symbol", "code"):
        if any(key in row for row in records):
            values = [row.get(key) for row in records]
            if (not all(isinstance(v, str) and v.strip() for v in values)
                    or len(set(values)) != 1):
                raise ValueError("COMPUTE_MULTIPLE_OR_MISSING_SUBJECTS")
    if field is None:
        if required:
            raise ValueError("COMPUTE_TIME_FIELD_REQUIRED")
        return False
    stamps = [parse_event_stamp(row.get(field)) for row in records]
    if any(stamp is None or (not day and stamp.utcoffset() is None) for stamp, day in stamps):
        raise ValueError("COMPUTE_TIME_LABEL_INVALID")
    if len({day for _, day in stamps}) != 1:
        raise ValueError("COMPUTE_MIXED_TIME_PRECISION")
    dates = [stamp for stamp, _ in stamps]
    if dates != sorted(set(dates)):
        raise ValueError("COMPUTE_TIME_ORDER_OR_DUPLICATE")
    return True


def run_factor_compute(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    try:
        records = _compute_records(operation, context)
    except ValueError as exc:
        return _compute_block(operation, str(exc))
    if not records:
        return _compute_block(operation, "NO_FACTOR_INPUT_RECORDS")
    spec = operation.parameters.get("factor_spec")
    if not isinstance(spec, dict):
        return _compute_block(operation, "FACTOR_SPEC_REQUIRED")
    field = spec.get("field")
    transform = str(spec.get("transform") or "IDENTITY").upper()
    if not isinstance(field, str) or not field.strip():
        return _compute_block(operation, "FACTOR_FIELD_REQUIRED")
    frame = pd.DataFrame(records)
    if field not in frame.columns:
        return _compute_block(operation, f"FACTOR_FIELD_MISSING:{field}")
    values_raw = [row.get(field) for row in records]
    if any(v is not None and not _is_finite_number(v) for v in values_raw):
        return _compute_block(operation, "FACTOR_NONFINITE_OR_NONNUMERIC_INPUT")
    values = pd.Series(values_raw, dtype="float64", index=frame.index)
    temporal = transform in {"PCT_CHANGE", "ROLLING_MEAN", "ROLLING_RETURN"}
    chronology = False
    if temporal:
        try:
            chronology = _chronological_rows(records, operation.parameters, required=True)
        except ValueError as exc:
            return _compute_block(operation, str(exc))
        key = "periods" if transform == "PCT_CHANGE" else "window"
        window = spec.get(key, 1 if transform == "PCT_CHANGE" else 20)
        if type(window) is not int or not (2 if transform == "ROLLING_MEAN" else 1) <= window <= 10000:
            return _compute_block(operation, "FACTOR_WINDOW_INVALID")
    if transform == "IDENTITY":
        factor = values
    elif transform == "RANK_PCT":
        factor = values.rank(method="average", pct=True)
    elif transform == "Z_SCORE":
        std = float(values.std(ddof=0))
        factor = (values - values.mean()) / std if std > 0 else values * 0.0
    elif transform == "PCT_CHANGE":
        factor = values.pct_change(periods=window, fill_method=None)
    elif transform == "ROLLING_MEAN":
        factor = values.rolling(window, min_periods=window).mean()
    elif transform == "ROLLING_RETURN":
        factor = values / values.shift(window) - 1.0
    else:
        return _compute_block(operation, f"UNSUPPORTED_FACTOR_TRANSFORM:{transform}")
    # Undefined ratios, missing observations and warmup are missing, never zeros.
    factor = factor.where(np.isfinite(factor))
    if not factor.notna().any():
        return _compute_block(operation, "FACTOR_NO_FINITE_OUTPUT")
    output_field = spec.get("output_field", "factor_value")
    if not isinstance(output_field, str) or not output_field.strip() or output_field in frame.columns:
        return _compute_block(operation, "FACTOR_OUTPUT_FIELD_COLLISION_OR_INVALID")
    frame[output_field] = factor
    output = json.loads(frame.to_json(orient="records", date_format="iso", force_ascii=False))
    finite = factor.dropna()
    statistics = {"count": int(finite.count()), "mean": float(finite.mean()),
                  "std": float(finite.std(ddof=0)), "min": float(finite.min()), "max": float(finite.max())}
    if not all(math.isfinite(v) for v in statistics.values()):
        return _compute_block(operation, "FACTOR_STATISTICS_NONFINITE")
    payload = {
        "factor_id": str(spec.get("factor_id") or operation.operation_id),
        "transform": transform, "source_field": field, "output_field": output_field,
        "records": output, "statistics": statistics,
        "missing_input_count": int(values.isna().sum()),
        "undefined_output_count": int(factor.isna().sum()),
        "missing_values_filled": False, "time_label_order_verified": chronology,
        "historical_vintage_verified": False, "pit_safe": False, "decision_authority": False,
    }
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    context.payloads[operation.operation_id] = payload
    return OperationResult(operation_id=operation.operation_id, status="PASS", exit_code=0,
                           artifacts=[_artifact(path)], metrics=statistics)


def _max_drawdown(equity: pd.Series) -> float | None:
    if equity.empty:
        return None
    # Initial wealth is one; a first-row fee or loss must count as drawdown.
    peaks = equity.cummax().clip(lower=1.0)
    return float((equity / peaks - 1.0).min())


def run_backtest(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    """Single-series arithmetic diagnostic; not a historical executable strategy."""
    parameters = operation.parameters
    try:
        records = _compute_records(operation, context)
        if not records:
            return _compute_block(operation, "NO_BACKTEST_INPUT_RECORDS")
        chronology = _chronological_rows(records, parameters,
                                         required="depends_on_operation_ids" in parameters)
    except ValueError as exc:
        return _compute_block(operation, str(exc))
    return_field = parameters.get("return_field", "return")
    weight_field = parameters.get("weight_field", "weight")
    if (not isinstance(return_field, str) or not return_field or not isinstance(weight_field, str)
            or not weight_field or return_field == weight_field):
        return _compute_block(operation, "BACKTEST_FIELDS_INVALID")
    returns_raw = [row.get(return_field) for row in records]
    weights_raw = [row.get(weight_field) for row in records]
    if not all(_is_finite_number(v) and v >= -1 for v in returns_raw):
        return _compute_block(operation, "BACKTEST_RETURN_MISSING_OR_INVALID")
    if not all(_is_finite_number(v) and 0 <= v <= 1 for v in weights_raw):
        return _compute_block(operation, "BACKTEST_WEIGHT_MISSING_OR_INVALID")
    cost_bps = parameters.get("cost_bps")
    if not _is_finite_number(cost_bps) or not 0 <= cost_bps < 10000:
        return _compute_block(operation, "BACKTEST_EXPLICIT_COST_ASSUMPTION_REQUIRED")
    periods_per_year = parameters.get("periods_per_year")
    if periods_per_year is not None and (type(periods_per_year) is not int or not 1 <= periods_per_year <= 100000):
        return _compute_block(operation, "BACKTEST_ANNUALIZATION_ASSUMPTION_INVALID")
    returns = pd.Series(returns_raw, dtype="float64")
    weights = pd.Series(weights_raw, dtype="float64")
    lag_weights = weights.shift(1, fill_value=0.0)
    gross = lag_weights * returns
    turnover = (weights - lag_weights).abs()
    net = gross - turnover * cost_bps / 10000.0
    if not np.isfinite(net).all() or (net <= -1).any():
        return _compute_block(operation, "BACKTEST_NONPOSITIVE_PERIOD_WEALTH")
    equity = (1.0 + net).cumprod()
    if not np.isfinite(equity).all() or (equity <= 0).any():
        return _compute_block(operation, "BACKTEST_NONFINITE_OR_NONPOSITIVE_WEALTH")
    n = len(net)
    total_return = float(equity.iloc[-1] - 1.0)
    annualized_return, annualized_vol, sharpe = None, None, None
    if periods_per_year is not None:
        try:
            annualized_return = math.expm1(math.log(float(equity.iloc[-1])) * periods_per_year / n)
            sd = float(net.std(ddof=1)) if n >= 2 else None
            annualized_vol = sd * math.sqrt(periods_per_year) if sd is not None else None
            sharpe = (float(net.mean()) / sd * math.sqrt(periods_per_year)
                      if sd is not None and sd > 0 else None)
        except (ArithmeticError, ValueError):
            return _compute_block(operation, "BACKTEST_ANNUALIZATION_NONFINITE")
    metrics = {
        "observations": n, "total_return": total_return,
        "annualized_return": annualized_return, "annualized_volatility": annualized_vol,
        "sharpe_zero_rf": sharpe, "max_drawdown": _max_drawdown(equity),
        "total_turnover": float(turnover.sum()), "cost_bps": float(cost_bps), "net_of_costs": True,
    }
    if any(v is not None and type(v) is not bool and not math.isfinite(v) for v in metrics.values()):
        return _compute_block(operation, "BACKTEST_METRICS_NONFINITE")
    payload = {
        "metrics": metrics,
        "assumptions": {
            "signal_lag_periods": 1, "periods_per_year": periods_per_year,
            "cost_applied_to_turnover": True, "cost_basis": "LINEAR_TARGET_WEIGHT_CHANGE_ASSUMPTION",
            "initial_weight": 0.0, "terminal_liquidation_assumed": False,
            "annualization_cadence_verified": False, "actual_costs_verified": False,
            "missing_returns_or_weights_imputed": False,
        },
        "time_label_order_verified": chronology,
        "research_only": True, "pit_safe": False, "historical_vintage_verified": False,
        "actual_trade_feasibility_verified": False, "decision_authority": False,
    }
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    context.payloads[operation.operation_id] = payload
    return OperationResult(operation_id=operation.operation_id, status="PASS", exit_code=0,
                           artifacts=[_artifact(path)], metrics=metrics)


_OPERATOR: dict[str, Callable[[pd.Series, float], pd.Series]] = {
    "GT": lambda series, value: series > value,
    "GE": lambda series, value: series >= value,
    "LT": lambda series, value: series < value,
    "LE": lambda series, value: series <= value,
}


_LIVE_SCAN_NUMERIC_FIELDS = {
    "latest_price",
    "pct_change",
    "volume",
    "amount",
    "amplitude",
    "turnover_rate",
    "pe_dynamic",
    "pb",
    "total_market_cap",
    "float_market_cap",
    "change_60d",
    "ytd_change",
}
_SCAN_RULE_KEYS = {"field", "operator", "threshold", "weight"}


def _scan_block(error: str) -> OperationResult:
    return OperationResult(
        operation_id="",
        status="BLOCK",
        exit_code=2,
        errors=[error],
    )


def _scan_as_of(value: object) -> str | None:
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value)
        return parsed.isoformat() if value == parsed.isoformat() else None
    except (TypeError, ValueError):
        return None


def _scan_scope(parameters: dict[str, object], key: str, default: str) -> str:
    value = parameters.get(key)
    return default if value is None or not str(value).strip() else str(value).strip().upper()


def _scan_input(
    operation: ExecutionOperation,
    context: WorkerContext,
) -> tuple[list[dict[str, object]], str, dict[str, object] | None, str | None] | OperationResult:
    parameters = operation.parameters
    has_dependency = "depends_on_operation_ids" in parameters
    has_inline = "inline_records" in parameters
    if has_dependency:
        if has_inline:
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_INLINE_CONFLICT")
        dependencies = parameters.get("depends_on_operation_ids")
        if not isinstance(dependencies, list) or len(dependencies) != 1:
            return _scan_block("OPPORTUNITY_SCAN_REQUIRES_SINGLE_DEPENDENCY")
        dependency_id = dependencies[0]
        if not isinstance(dependency_id, str):
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_ID_INVALID")
        provenance = context.completed_operations.get(dependency_id)
        if provenance is None:
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_NOT_COMPLETED")
        if provenance.get("kind") != "MARKET_UNIVERSE":
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_KIND_INVALID")
        if provenance.get("status") not in {"PASS", "WARN"}:
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_STATUS_INVALID")
        operation_as_of = _scan_as_of(parameters.get("as_of"))
        request_as_of = _scan_as_of(context.request_as_of)
        if (
            operation_as_of is None
            or request_as_of is None
            or _scan_as_of(provenance.get("as_of")) != operation_as_of
            or operation_as_of != request_as_of
        ):
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_AS_OF_INVALID")
        payload = context.payloads.get(dependency_id)
        if not isinstance(payload, dict):
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_PAYLOAD_INVALID")
        if (
            payload.get("source") != "public_market_data"
            or payload.get("public_data_only") is not True
            or payload.get("decision_authority") is not False
        ):
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_PAYLOAD_INVALID")
        if (
            _scan_scope(parameters, "market", "CN_A") != provenance.get("market")
            or _scan_scope(parameters, "asset_type", "STOCK") != provenance.get("asset_type")
            or _scan_scope(parameters, "market", "CN_A") != payload.get("market")
            or _scan_scope(parameters, "asset_type", "STOCK") != payload.get("asset_type")
        ):
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_SCOPE_INVALID")
        payload_as_of = _scan_as_of(payload.get("as_of"))
        if (
            operation_as_of is None
            or request_as_of is None
            or payload_as_of is None
            or operation_as_of != request_as_of
            or operation_as_of != payload_as_of
        ):
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_AS_OF_INVALID")
        records = payload.get("records")
        if not isinstance(records, list) or not records or not all(isinstance(item, dict) for item in records):
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_RECORDS_MISSING")
        listing_crosscheck = payload.get("listing_crosscheck")
        listing_status = listing_crosscheck.get("status") if isinstance(listing_crosscheck, dict) else None
        dependency_evidence = {
            "operation_id": dependency_id,
            "kind": provenance.get("kind"),
            "status": provenance.get("status"),
            "as_of": operation_as_of,
            "market": payload.get("market"),
            "asset_type": payload.get("asset_type"),
            "source": payload.get("source"),
            "provider": payload.get("provider"),
            "primary_provider": payload.get("primary_provider"),
            "quote_trade_date_status": payload.get("quote_trade_date_status"),
            "listing_crosscheck": {"status": listing_status},
            "quality_flags": [
                item for item in payload.get("quality_flags", [])[:16] if isinstance(item, str)
            ],
            "warnings": [item for item in payload.get("warnings", [])[:16] if isinstance(item, str)],
        }
        return [dict(item) for item in records], "LIVE_MARKET_UNIVERSE", dependency_evidence, str(
            provenance.get("status")
        )
    if not has_inline:
        return _scan_block("OPPORTUNITY_SCAN_REQUIRES_RECORDS")
    records = parameters.get("inline_records")
    if not isinstance(records, list) or not records or not all(isinstance(item, dict) for item in records):
        return _scan_block("OPPORTUNITY_SCAN_INLINE_RECORDS_INVALID")
    return [dict(item) for item in records], "INLINE_SYNTHETIC", None, None


def _is_finite_number(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(float(value))


def _is_missing_value(value: object) -> bool:
    if value is None:
        return True
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return isinstance(missing, (bool, np.bool_)) and bool(missing)


def _validate_scan_semantics(parameters: dict[str, object]) -> str | None:
    if (
        "ranking_semantics" in parameters
        and parameters["ranking_semantics"] != "RESEARCH_PRIORITY_NOT_RETURN_FORECAST"
    ):
        return "OPPORTUNITY_SCAN_SEMANTICS_INVALID"
    if (
        "rule_origin" in parameters
        and parameters["rule_origin"] not in {"USER_PROVIDED_RESEARCH_FILTER", "SYSTEM_RESEARCH_FILTER"}
    ):
        return "OPPORTUNITY_SCAN_SEMANTICS_INVALID"
    return None


def _validate_scan_rules(
    parameters: dict[str, object],
    frame: pd.DataFrame,
    input_mode: str,
) -> tuple[list[dict[str, object]], int] | str:
    rules = parameters.get("rules")
    if not isinstance(rules, list) or not 1 <= len(rules) <= 32:
        return "OPPORTUNITY_SCAN_RULE_COUNT_INVALID"
    applied_rules: list[dict[str, object]] = []
    for index, raw_rule in enumerate(rules):
        if not isinstance(raw_rule, dict):
            return f"OPPORTUNITY_SCAN_RULE_NOT_OBJECT:{index}"
        extra = sorted(set(raw_rule) - _SCAN_RULE_KEYS)
        if extra:
            return f"OPPORTUNITY_SCAN_RULE_KEYS_INVALID:{index}"
        field = raw_rule.get("field")
        if not isinstance(field, str) or not field.strip():
            return f"OPPORTUNITY_SCAN_RULE_FIELD_INVALID:{index}"
        field = field.strip()
        if input_mode == "LIVE_MARKET_UNIVERSE" and field not in _LIVE_SCAN_NUMERIC_FIELDS:
            return f"OPPORTUNITY_SCAN_LIVE_FIELD_INVALID:{field}"
        if field not in frame.columns:
            return f"OPPORTUNITY_SCAN_RULE_FIELD_MISSING:{field}"
        values = frame[field].tolist()
        if input_mode == "LIVE_MARKET_UNIVERSE":
            present_values = [value for value in values if not _is_missing_value(value)]
            if not present_values:
                return f"OPPORTUNITY_SCAN_RULE_FIELD_NO_VALID_NUMERIC:{field}"
            if not all(_is_finite_number(value) for value in present_values):
                return f"OPPORTUNITY_SCAN_RULE_FIELD_NOT_NUMERIC:{field}"
        elif not all(_is_finite_number(value) for value in values):
            return f"OPPORTUNITY_SCAN_RULE_FIELD_NOT_NUMERIC:{field}"
        operator = raw_rule.get("operator")
        if not isinstance(operator, str) or operator not in _OPERATOR:
            return f"OPPORTUNITY_SCAN_RULE_OPERATOR_INVALID:{index}"
        if "threshold" not in raw_rule or not _is_finite_number(raw_rule["threshold"]):
            return f"OPPORTUNITY_SCAN_RULE_THRESHOLD_INVALID:{index}"
        threshold = float(raw_rule["threshold"])
        if "weight" not in raw_rule:
            weight = 1.0
        elif not _is_finite_number(raw_rule["weight"]) or float(raw_rule["weight"]) < 0:
            return f"OPPORTUNITY_SCAN_RULE_WEIGHT_INVALID:{index}"
        else:
            weight = float(raw_rule["weight"])
        applied_rules.append(
            {"field": field, "operator": operator, "threshold": threshold, "weight": weight}
        )
    top_n = parameters.get("top_n", 50)
    if not isinstance(top_n, int) or isinstance(top_n, bool) or not 1 <= top_n <= 1000:
        return "OPPORTUNITY_SCAN_TOP_N_INVALID"
    return applied_rules, top_n


def run_opportunity_scan(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    semantic_error = _validate_scan_semantics(operation.parameters)
    if semantic_error is not None:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=[semantic_error],
        )
    scan_input = _scan_input(operation, context)
    if isinstance(scan_input, OperationResult):
        return scan_input.model_copy(update={"operation_id": operation.operation_id})
    records, input_mode, dependency_evidence, dependency_status = scan_input
    frame = pd.DataFrame(records)
    validated = _validate_scan_rules(operation.parameters, frame, input_mode)
    if isinstance(validated, str):
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=[validated],
        )
    applied_rules, top_n = validated
    score = pd.Series(0.0, index=frame.index)
    matched_count = pd.Series(0, index=frame.index)
    for rule in applied_rules:
        field = str(rule["field"])
        operator = str(rule["operator"])
        threshold = float(rule["threshold"])
        weight = float(rule["weight"])
        matches = _OPERATOR[operator](_numeric(frame[field]), threshold).fillna(False)
        score = score + matches.astype(float) * weight
        matched_count = matched_count + matches.astype(int)
    frame["research_priority_score"] = score
    frame["matched_rule_count"] = matched_count
    sort_fields = ["research_priority_score", "matched_rule_count"]
    frame = frame.sort_values(sort_fields, ascending=[False, False], kind="stable")
    output = json.loads(frame.head(top_n).to_json(orient="records", date_format="iso", force_ascii=False))
    payload = {
        "candidates": output,
        "rules": applied_rules,
        "candidate_count": len(output),
        "ranking_semantics": "RESEARCH_PRIORITY_NOT_RETURN_FORECAST",
        "input_mode": input_mode,
        "rule_origin": operation.parameters.get("rule_origin", "UNSPECIFIED_RESEARCH_FILTER"),
        "screened_count": len(frame),
        "research_only": True,
        "pit_safe": False,
        "decision_authority": False,
    }
    if dependency_evidence is not None:
        payload["dependency_evidence"] = dependency_evidence
    warnings = (
        ["OPPORTUNITY_SCAN_DEPENDENCY_WARN"]
        if dependency_status == "WARN"
        else []
    )
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    context.payloads[operation.operation_id] = payload
    return OperationResult(
        operation_id=operation.operation_id,
        status="WARN" if warnings else "PASS",
        exit_code=0,
        artifacts=[_artifact(path)],
        warnings=warnings,
        metrics={
            "candidate_count": len(output),
            "rule_count": len(applied_rules),
            "input_mode": input_mode,
        },
    )


def run_test_suite(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    suites = operation.parameters.get("suites") or ["pytest"]
    if not isinstance(suites, list):
        raise ValueError("TEST_SUITE suites must be a list")
    allowlist = {
        "pytest": [sys.executable, "-m", "pytest", "-q"],
        "compile": [sys.executable, "-m", "compileall", "-q", "src"],
        "ruff": [sys.executable, "-m", "ruff", "check", "."],
    }
    unknown = [str(item) for item in suites if str(item) not in allowlist]
    if unknown:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=["UNSAFE_OR_UNKNOWN_TEST_SUITE:" + ",".join(unknown)],
        )
    logs: list[str] = []
    failures: list[str] = []
    for suite in [str(item) for item in suites]:
        completed = subprocess.run(
            allowlist[suite],
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        logs.append(f"## {suite}\nexit={completed.returncode}\n{completed.stdout}\n{completed.stderr}")
        if completed.returncode != 0:
            failures.append(f"{suite}:exit={completed.returncode}")
    path = context.output_dir / f"{operation.operation_id}.log"
    path.write_text("\n\n".join(logs), encoding="utf-8")
    payload = {
        "suites": [str(item) for item in suites],
        "failures": failures,
        "decision_authority": False,
    }
    json_path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(json_path, payload)
    return OperationResult(
        operation_id=operation.operation_id,
        status="BLOCK" if failures else "PASS",
        exit_code=2 if failures else 0,
        artifacts=[_artifact(json_path), _artifact(path, "text/plain")],
        metrics={"suite_count": len(suites), "failure_count": len(failures)},
        errors=failures,
    )
