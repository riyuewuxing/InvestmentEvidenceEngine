from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from .contracts import ArtifactRef, ExecutionOperation, OperationResult
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
    records = _records(operation, context)
    cutoff_raw = operation.parameters.get("as_of")
    if cutoff_raw is None:
        raise ValueError("PIT_REPLAY requires as_of")
    cutoff = pd.Timestamp(str(cutoff_raw))
    available_field = str(operation.parameters.get("available_at_field") or "available_at")
    published_field = str(operation.parameters.get("published_at_field") or "published_at")
    strict = bool(operation.parameters.get("strict", True))

    eligible: list[dict[str, object]] = []
    future: list[int] = []
    missing_availability: list[int] = []
    for index, record in enumerate(records):
        available = record.get(available_field)
        if available is None:
            available = record.get(published_field)
        if available is None:
            missing_availability.append(index)
            continue
        timestamp = pd.to_datetime(available, errors="coerce")
        if pd.isna(timestamp):
            missing_availability.append(index)
            continue
        if timestamp > cutoff:
            future.append(index)
        else:
            eligible.append(record)

    blockers: list[str] = []
    if strict and missing_availability:
        blockers.append(f"MISSING_AVAILABILITY:{len(missing_availability)}")
    if future:
        blockers.append(f"FUTURE_RECORDS_REJECTED:{len(future)}")
    if not records:
        blockers.append("NO_REPLAY_RECORDS")

    payload = {
        "as_of": cutoff.isoformat(),
        "input_count": len(records),
        "eligible_count": len(eligible),
        "future_rejected_count": len(future),
        "missing_availability_count": len(missing_availability),
        "eligible_records": eligible,
        "strict": strict,
        "pit_safe": not blockers,
        "decision_authority": False,
    }
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    context.payloads[operation.operation_id] = payload
    return OperationResult(
        operation_id=operation.operation_id,
        status="BLOCK" if blockers else "PASS",
        exit_code=2 if blockers else 0,
        artifacts=[_artifact(path)],
        metrics={key: payload[key] for key in (
            "input_count", "eligible_count", "future_rejected_count", "missing_availability_count", "pit_safe"
        )},
        errors=blockers,
    )


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def run_factor_compute(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    records = _records(operation, context)
    if not records:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=["NO_FACTOR_INPUT_RECORDS"],
        )
    spec = operation.parameters.get("factor_spec")
    if not isinstance(spec, dict):
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=["FACTOR_SPEC_REQUIRED"],
        )
    field = str(spec.get("field") or "")
    transform = str(spec.get("transform") or "IDENTITY").upper()
    if not field:
        raise ValueError("factor_spec.field is required")
    frame = pd.DataFrame(records)
    if field not in frame.columns:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=[f"FACTOR_FIELD_MISSING:{field}"],
        )
    values = _numeric(frame[field])
    if transform == "IDENTITY":
        factor = values
    elif transform == "RANK_PCT":
        factor = values.rank(method="average", pct=True)
    elif transform == "Z_SCORE":
        std = float(values.std(ddof=0))
        factor = (values - values.mean()) / std if std > 0 else values * 0.0
    elif transform == "PCT_CHANGE":
        periods = max(1, int(spec.get("periods") or 1))
        factor = values.pct_change(periods=periods)
    elif transform == "ROLLING_MEAN":
        window = max(2, int(spec.get("window") or 20))
        factor = values.rolling(window).mean()
    elif transform == "ROLLING_RETURN":
        window = max(1, int(spec.get("window") or 20))
        factor = values / values.shift(window) - 1.0
    else:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=[f"UNSUPPORTED_FACTOR_TRANSFORM:{transform}"],
        )
    output_field = str(spec.get("output_field") or "factor_value")
    frame[output_field] = factor
    output = json.loads(frame.to_json(orient="records", date_format="iso", force_ascii=False))
    finite = pd.to_numeric(frame[output_field], errors="coerce").dropna()
    payload = {
        "factor_id": str(spec.get("factor_id") or operation.operation_id),
        "transform": transform,
        "source_field": field,
        "output_field": output_field,
        "records": output,
        "statistics": {
            "count": int(finite.count()),
            "mean": float(finite.mean()) if not finite.empty else None,
            "std": float(finite.std(ddof=0)) if not finite.empty else None,
            "min": float(finite.min()) if not finite.empty else None,
            "max": float(finite.max()) if not finite.empty else None,
        },
        "decision_authority": False,
    }
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    context.payloads[operation.operation_id] = payload
    return OperationResult(
        operation_id=operation.operation_id,
        status="PASS",
        exit_code=0,
        artifacts=[_artifact(path)],
        metrics=payload["statistics"],
    )


def _max_drawdown(equity: pd.Series) -> float | None:
    if equity.empty:
        return None
    peaks = equity.cummax()
    drawdown = equity / peaks - 1.0
    return float(drawdown.min())


def run_backtest(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    records = _records(operation, context)
    if not records:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=["NO_BACKTEST_INPUT_RECORDS"],
        )
    frame = pd.DataFrame(records)
    return_field = str(operation.parameters.get("return_field") or "return")
    weight_field = str(operation.parameters.get("weight_field") or "weight")
    if return_field not in frame.columns:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=[f"BACKTEST_RETURN_FIELD_MISSING:{return_field}"],
        )
    returns = _numeric(frame[return_field]).fillna(0.0)
    weights = _numeric(frame[weight_field]).fillna(0.0) if weight_field in frame.columns else pd.Series(1.0, index=frame.index)
    lag_weights = weights.shift(1).fillna(0.0)
    gross = lag_weights * returns
    turnover = (weights - weights.shift(1).fillna(0.0)).abs()
    cost_bps = float(operation.parameters.get("cost_bps") or 0.0)
    net = gross - turnover * cost_bps / 10000.0
    equity = (1.0 + net).cumprod()
    periods_per_year = max(1, int(operation.parameters.get("periods_per_year") or 252))
    n = len(net)
    total_return = float(equity.iloc[-1] - 1.0) if n else 0.0
    annualized_return = float(equity.iloc[-1] ** (periods_per_year / n) - 1.0) if n and equity.iloc[-1] > 0 else None
    annualized_vol = float(net.std(ddof=1) * math.sqrt(periods_per_year)) if net.count() >= 2 else None
    sharpe = (
        float(net.mean() / net.std(ddof=1) * math.sqrt(periods_per_year))
        if net.count() >= 2 and float(net.std(ddof=1)) > 0
        else None
    )
    metrics = {
        "observations": n,
        "total_return": total_return,
        "annualized_return": annualized_return,
        "annualized_volatility": annualized_vol,
        "sharpe_zero_rf": sharpe,
        "max_drawdown": _max_drawdown(equity),
        "total_turnover": float(turnover.sum()),
        "cost_bps": cost_bps,
        "net_of_costs": True,
    }
    payload = {
        "metrics": metrics,
        "assumptions": {
            "signal_lag_periods": 1,
            "periods_per_year": periods_per_year,
            "cost_applied_to_turnover": True,
        },
        "decision_authority": False,
    }
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    context.payloads[operation.operation_id] = payload
    return OperationResult(
        operation_id=operation.operation_id,
        status="PASS",
        exit_code=0,
        artifacts=[_artifact(path)],
        metrics=metrics,
    )


_OPERATOR: dict[str, Callable[[pd.Series, float], pd.Series]] = {
    "GT": lambda series, value: series > value,
    "GE": lambda series, value: series >= value,
    "LT": lambda series, value: series < value,
    "LE": lambda series, value: series <= value,
}


def run_opportunity_scan(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    records = _records(operation, context)
    rules = operation.parameters.get("rules")
    if not records or not isinstance(rules, list) or not rules:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=["OPPORTUNITY_SCAN_REQUIRES_RECORDS_AND_RULES"],
        )
    frame = pd.DataFrame(records)
    score = pd.Series(0.0, index=frame.index)
    matched_count = pd.Series(0, index=frame.index)
    applied_rules: list[dict[str, object]] = []
    for raw_rule in rules:
        if not isinstance(raw_rule, dict):
            continue
        field = str(raw_rule.get("field") or "")
        operator = str(raw_rule.get("operator") or "GE").upper()
        if field not in frame.columns or operator not in _OPERATOR:
            return OperationResult(
                operation_id=operation.operation_id,
                status="BLOCK",
                exit_code=2,
                errors=[f"INVALID_SCAN_RULE:{field}:{operator}"],
            )
        threshold = float(raw_rule.get("threshold") or 0.0)
        weight = float(raw_rule.get("weight") or 1.0)
        matches = _OPERATOR[operator](_numeric(frame[field]), threshold).fillna(False)
        score = score + matches.astype(float) * weight
        matched_count = matched_count + matches.astype(int)
        applied_rules.append({"field": field, "operator": operator, "threshold": threshold, "weight": weight})
    frame["research_priority_score"] = score
    frame["matched_rule_count"] = matched_count
    sort_fields = ["research_priority_score", "matched_rule_count"]
    frame = frame.sort_values(sort_fields, ascending=[False, False], kind="stable")
    top_n = max(1, min(int(operation.parameters.get("top_n") or 50), 1000))
    output = json.loads(frame.head(top_n).to_json(orient="records", date_format="iso", force_ascii=False))
    payload = {
        "candidates": output,
        "rules": applied_rules,
        "candidate_count": len(output),
        "ranking_semantics": "RESEARCH_PRIORITY_NOT_RETURN_FORECAST",
        "decision_authority": False,
    }
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    context.payloads[operation.operation_id] = payload
    return OperationResult(
        operation_id=operation.operation_id,
        status="PASS",
        exit_code=0,
        artifacts=[_artifact(path)],
        metrics={"candidate_count": len(output), "rule_count": len(applied_rules)},
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
