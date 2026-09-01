from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
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
    as_of = date.fromisoformat(str(operation.parameters.get("as_of"))[:10])
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

    require_pit = bool(operation.parameters.get("pit_required", False))
    # Some ownership endpoints expose report/effective dates but not a verified public-availability
    # timestamp. Never certify historical PIT safety from those fields alone.
    pit_safe = not require_pit or as_of >= date.today()
    if require_pit and as_of < date.today():
        warnings.append("HISTORICAL_OWNERSHIP_AVAILABILITY_NOT_FULLY_VERIFIED")

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
    scope = str(operation.parameters.get("portfolio_scope") or "synthetic").lower()
    if scope not in {"synthetic", "generic", "public_model"}:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=["PORTFOLIO_MATH_PRIVATE_SCOPE_FORBIDDEN"],
        )

    assets = operation.parameters.get("assets")
    if not isinstance(assets, list) or not assets or not all(isinstance(item, dict) for item in assets):
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=["PORTFOLIO_MATH_REQUIRES_PUBLIC_OR_SYNTHETIC_ASSETS"],
        )

    names = [str(item.get("asset_id") or f"asset_{i}") for i, item in enumerate(assets)]
    weights = np.asarray([float(item.get("weight") or 0.0) for item in assets], dtype=float)
    if not np.isfinite(weights).all():
        raise ValueError("weights must be finite")
    weight_sum = float(weights.sum())
    if abs(weight_sum) < 1e-12:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=["PORTFOLIO_WEIGHT_SUM_ZERO"],
        )
    normalized = weights / weight_sum
    hhi = float(np.square(normalized).sum())
    effective_n = float(1.0 / hhi) if hhi > 0 else None

    covariance_raw = operation.parameters.get("covariance_matrix")
    portfolio_volatility: float | None = None
    marginal_risk: list[dict[str, object]] = []
    if covariance_raw is not None:
        covariance = np.asarray(covariance_raw, dtype=float)
        n = len(normalized)
        if covariance.shape != (n, n) or not np.isfinite(covariance).all():
            return OperationResult(
                operation_id=operation.operation_id,
                status="BLOCK",
                exit_code=2,
                errors=["INVALID_COVARIANCE_MATRIX"],
            )
        variance = float(normalized @ covariance @ normalized)
        if variance < -1e-10:
            return OperationResult(
                operation_id=operation.operation_id,
                status="BLOCK",
                exit_code=2,
                errors=["NEGATIVE_PORTFOLIO_VARIANCE"],
            )
        variance = max(variance, 0.0)
        portfolio_volatility = float(np.sqrt(variance))
        component = normalized * (covariance @ normalized)
        if portfolio_volatility and portfolio_volatility > 0:
            contributions = component / portfolio_volatility
        else:
            contributions = np.zeros_like(normalized)
        marginal_risk = [
            {
                "asset_id": names[i],
                "normalized_weight": float(normalized[i]),
                "component_volatility_contribution": float(contributions[i]),
            }
            for i in range(len(names))
        ]

    expected_raw = [item.get("expected_return") for item in assets]
    expected_return: float | None = None
    if all(value is not None for value in expected_raw):
        expected = np.asarray([float(value) for value in expected_raw], dtype=float)
        expected_return = float(normalized @ expected)

    payload = {
        "scope": scope,
        "assets": [
            {"asset_id": names[i], "input_weight": float(weights[i]), "normalized_weight": float(normalized[i])}
            for i in range(len(names))
        ],
        "metrics": {
            "input_weight_sum": weight_sum,
            "hhi": hhi,
            "effective_number_of_assets": effective_n,
            "expected_return": expected_return,
            "portfolio_volatility": portfolio_volatility,
        },
        "risk_contributions": marginal_risk,
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
        metrics=payload["metrics"],
    )
