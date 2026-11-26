from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

import numpy as np
import pandas as pd

from .contracts import ArtifactRef, ExecutionOperation, OperationResult
from .workers import WorkerContext


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _artifact(path: Path) -> ArtifactRef:
    return ArtifactRef(
        path=path.name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        media_type="application/json",
        size_bytes=path.stat().st_size,
    )


def _symbol(operation: ExecutionOperation) -> str:
    values = operation.parameters.get("subject_ids") or []
    if not isinstance(values, list) or not values:
        raise ValueError("operation requires subject_ids")
    return str(values[0]).strip().zfill(6)


def _records(frame: pd.DataFrame | None) -> list[dict[str, object]]:
    if frame is None or frame.empty:
        return []
    return json.loads(frame.to_json(orient="records", date_format="iso", force_ascii=False))


def run_ownership_flow(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    symbol = _symbol(operation)
    raw_as_of = operation.parameters.get("as_of")
    if not isinstance(raw_as_of, str):
        raise ValueError("OWNERSHIP_EXACT_DATE_REQUIRED")
    as_of = date.fromisoformat(raw_as_of)
    if raw_as_of != as_of.isoformat() or as_of > datetime.now(ZoneInfo("Asia/Shanghai")).date():
        raise ValueError("OWNERSHIP_EXACT_NONFUTURE_DATE_REQUIRED")
    history_days = max(30, min(int(operation.parameters.get("history_days") or 730), 3650))
    start = as_of - timedelta(days=history_days)
    warnings: list[str] = []
    sources: dict[str, list[dict[str, object]]] = {}

    try:
        import akshare as ak
    except ImportError as exc:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=[f"AKSHARE_NOT_INSTALLED:{exc}"],
        )

    try:
        frame = ak.stock_share_change_cninfo(
            symbol=symbol,
            start_date=start.strftime("%Y%m%d"),
            end_date=as_of.strftime("%Y%m%d"),
        )
        sources["cninfo_share_structure_change"] = _records(frame)
    except Exception as exc:
        warnings.append(f"SHARE_STRUCTURE_UNAVAILABLE:{type(exc).__name__}:{exc}")

    try:
        holder_fn = getattr(ak, "stock_zh_a_gdhs_detail_em", None)
        if holder_fn is not None:
            frame = holder_fn(symbol=symbol)
            rows = _records(frame)
            filtered: list[dict[str, object]] = []
            for row in rows:
                raw_date = row.get("股东户数统计截止日") or row.get("截止日期") or row.get("股东户数公告日期")
                if raw_date is None:
                    filtered.append(row)
                    continue
                stamp = pd.to_datetime(raw_date, errors="coerce")
                if pd.isna(stamp) or stamp.date() <= as_of:
                    filtered.append(row)
            sources["shareholder_count"] = filtered
        else:
            warnings.append("SHAREHOLDER_COUNT_API_NOT_AVAILABLE")
    except Exception as exc:
        warnings.append(f"SHAREHOLDER_COUNT_UNAVAILABLE:{type(exc).__name__}:{exc}")

    # Northbound detail is a useful public flow proxy but the upstream endpoint only exposes
    # a recent window. Treat absence as a warning rather than inventing historical data.
    try:
        northbound_start = max(start, as_of - timedelta(days=100))
        frame = ak.stock_hsgt_individual_detail_em(
            symbol=symbol,
            start_date=northbound_start.strftime("%Y%m%d"),
            end_date=as_of.strftime("%Y%m%d"),
        )
        sources["northbound_holding_detail"] = _records(frame)
    except Exception as exc:
        warnings.append(f"NORTHBOUND_DETAIL_UNAVAILABLE:{type(exc).__name__}:{exc}")

    require_pit = operation.parameters.get("pit_required", False)
    if type(require_pit) is not bool:
        raise ValueError("OWNERSHIP_PIT_REQUIRED_MUST_BE_BOOLEAN")
    # The live endpoints do not provide verified capture vintage or exact availability.
    # Current-day scope is not proof of prior intraday visibility either.
    pit_safe = False
    warnings.append("OWNERSHIP_AVAILABILITY_AND_HISTORICAL_VINTAGE_UNVERIFIED")

    total_rows = sum(len(items) for items in sources.values())
    if total_rows == 0:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=["NO_OWNERSHIP_FLOW_EVIDENCE"],
            warnings=warnings,
        )

    payload = {
        "symbol": symbol,
        "as_of": as_of.isoformat(),
        "observed_at": datetime.now(UTC).isoformat(),
        "date_scope": "REQUESTED_REPORT_WINDOW_NOT_PIT_FILTER",
        "historical_vintage_verified": False,
        "sources": sources,
        "source_row_counts": {key: len(value) for key, value in sources.items()},
        "pit_safe": pit_safe,
        "warnings": warnings,
        "decision_authority": False,
    }
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    context.payloads[operation.operation_id] = payload
    status = "PASS" if not warnings and pit_safe else "WARN"
    if require_pit and not pit_safe:
        status = "BLOCK"
    return OperationResult(
        operation_id=operation.operation_id,
        status=status,
        exit_code=0 if status != "BLOCK" else 2,
        artifacts=[_artifact(path)],
        metrics={"source_count": len(sources), "rows": total_rows, "pit_safe": pit_safe},
        warnings=warnings,
        errors=["OWNERSHIP_PIT_NOT_VERIFIED"] if status == "BLOCK" else [],
    )


def run_portfolio_math(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    """Long-only normalized hypothetical allocation; no real portfolio or forecast."""
    def blocked(reason):
        return OperationResult(operation_id=operation.operation_id, status="BLOCK",
                               exit_code=2, errors=[reason])

    scope = str(operation.parameters.get("portfolio_scope") or "synthetic").lower()
    if scope not in {"synthetic", "generic", "public_model"}:
        return blocked("PORTFOLIO_MATH_PRIVATE_SCOPE_FORBIDDEN")
    assets = operation.parameters.get("assets")
    if (not isinstance(assets, list) or not 1 <= len(assets) <= 256
            or not all(isinstance(item, dict) for item in assets)):
        return blocked("PORTFOLIO_MATH_REQUIRES_PUBLIC_OR_SYNTHETIC_ASSETS")
    names = [item.get("asset_id") for item in assets]
    if (any(not isinstance(name, str) or not name.strip() or name != name.strip() for name in names)
            or len(set(names)) != len(names)):
        return blocked("PORTFOLIO_ASSET_IDENTITY_INVALID")
    raw_weights = [item.get("weight") for item in assets]
    if any(type(v) not in (int, float) for v in raw_weights):
        return blocked("PORTFOLIO_WEIGHT_REQUIRED_NUMERIC")
    weights = np.asarray(raw_weights, dtype=float)
    if not np.isfinite(weights).all() or np.any(weights < 0):
        return blocked("PORTFOLIO_LONG_ONLY_FINITE_WEIGHTS_REQUIRED")
    weight_sum = float(weights.sum())
    if not np.isfinite(weight_sum) or weight_sum <= 0:
        return blocked("PORTFOLIO_WEIGHT_SUM_INVALID")
    normalized = weights / weight_sum
    hhi = float(np.square(normalized).sum())
    effective_n = float(1.0 / hhi)
    covariance_raw = operation.parameters.get("covariance_matrix")
    portfolio_volatility = None
    contributions = []
    if covariance_raw is not None:
        n = len(normalized)
        if (not isinstance(covariance_raw, list) or len(covariance_raw) != n
                or any(not isinstance(row, list) or len(row) != n
                       or any(type(v) not in (int, float) for v in row) for row in covariance_raw)):
            return blocked("INVALID_COVARIANCE_MATRIX")
        covariance = np.asarray(covariance_raw, dtype=float)
        if not np.isfinite(covariance).all():
            return blocked("INVALID_COVARIANCE_MATRIX")
        # Relative tolerances on the matrix scale, not on an absolute unit size.
        scale = float(np.max(np.abs(covariance)))
        if scale == 0:
            portfolio_volatility = 0.0
        else:
            scaled = covariance / scale
            if not np.allclose(scaled, scaled.T, rtol=0, atol=1e-12):
                return blocked("COVARIANCE_NOT_SYMMETRIC")
            scaled = (scaled + scaled.T) * 0.5
            if np.any(np.diag(scaled) < 0) or float(np.linalg.eigvalsh(scaled)[0]) < -1e-12:
                return blocked("COVARIANCE_NOT_POSITIVE_SEMIDEFINITE")
            direction = scaled @ normalized
            variance = float(normalized @ direction)
            if variance < -1e-12:
                return blocked("NEGATIVE_PORTFOLIO_VARIANCE")
            root = float(np.sqrt(max(variance, 0.0)))
            portfolio_volatility = float(np.sqrt(scale)) * root
            if root > 0:
                component = normalized * direction / root * np.sqrt(scale)
                if not np.isfinite(component).all():
                    return blocked("NONFINITE_PORTFOLIO_CONTRIBUTION")
                contributions = [
                    {"asset_id": names[i], "normalized_weight": float(normalized[i]),
                     "component_volatility_contribution": float(component[i])}
                    for i in range(n)
                ]
        # A zero-volatility derivative is undefined, not a zero marginal risk.
        if portfolio_volatility == 0:
            contributions = []
    expected_raw = [item.get("expected_return") for item in assets]
    if any(v is not None and (type(v) not in (int, float) or not np.isfinite(float(v)))
           for v in expected_raw):
        return blocked("INVALID_EXPECTED_RETURN_ASSUMPTION")
    expected_return = None
    if all(v is not None for v in expected_raw):
        expected_return = float(normalized @ np.asarray(expected_raw, dtype=float))
        if not np.isfinite(expected_return):
            return blocked("NONFINITE_PORTFOLIO_EXPECTED_RETURN")
    payload = {
        "scope": scope,
        "assets": [{"asset_id": names[i], "input_weight": float(weights[i]),
                    "normalized_weight": float(normalized[i])} for i in range(len(names))],
        "metrics": {"input_weight_sum": weight_sum, "hhi": hhi,
                    "effective_number_of_assets": effective_n,
                    "expected_return": expected_return,
                    "portfolio_volatility": portfolio_volatility},
        "risk_contributions": contributions,
        "risk_contribution_status": ("COMPONENT_VOLATILITY_ONLY" if contributions else
            "UNDEFINED_ZERO_VOLATILITY" if portfolio_volatility == 0 else "COVARIANCE_NOT_SUPPLIED"),
        "assumption_basis": "CALLER_SUPPLIED_LONG_ONLY_WEIGHTS_AND_COVARIANCE",
        "forecast_validated": False,
        "formal_marginal_portfolio_risk_estimated": False,
        "decision_authority": False,
    }
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    context.payloads[operation.operation_id] = payload
    return OperationResult(operation_id=operation.operation_id, status="PASS", exit_code=0,
                           artifacts=[_artifact(path)], metrics=payload["metrics"])
