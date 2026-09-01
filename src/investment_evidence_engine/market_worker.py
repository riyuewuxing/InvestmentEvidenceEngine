from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .contracts import ArtifactRef, ExecutionOperation, OperationResult
from .providers import BaoStockProvider, ProviderError, normalize_ohlcv
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


def _symbol(parameters: dict[str, object]) -> str:
    values = parameters.get("subject_ids") or []
    if not isinstance(values, list) or not values:
        raise ValueError("MARKET_DATA requires subject_ids")
    return str(values[0]).strip().zfill(6)


def _as_of(parameters: dict[str, object]) -> date:
    raw = parameters.get("as_of")
    if raw is None:
        raise ValueError("MARKET_DATA requires as_of")
    return date.fromisoformat(str(raw)[:10])


def _sina_code(symbol: str) -> str:
    if len(symbol) != 6 or not symbol.isdigit():
        raise ProviderError(f"unsupported A-share symbol: {symbol}")
    if symbol.startswith(("5", "6", "9")):
        return f"sh{symbol}"
    if symbol.startswith(("0", "1", "2", "3")):
        return f"sz{symbol}"
    raise ProviderError(f"Sina fallback cannot infer exchange for {symbol}")


def _akshare_daily_resilient(
    symbol: str,
    start: date,
    end: date,
    adjust: str,
) -> tuple[pd.DataFrame, str, list[str]]:
    try:
        import akshare as ak
    except ImportError as exc:
        raise ProviderError("akshare is not installed") from exc

    errors: list[str] = []
    try:
        raw = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust=adjust,
        )
        if raw is not None and not raw.empty:
            mapping = {
                "日期": "date",
                "开盘": "open",
                "最高": "high",
                "最低": "low",
                "收盘": "close",
                "成交量": "volume",
                "成交额": "amount",
                "换手率": "turnover",
            }
            frame = normalize_ohlcv(raw.rename(columns=mapping))
            return frame, "eastmoney", errors
        errors.append("eastmoney:empty")
    except Exception as exc:  # noqa: BLE001 - third-party provider boundary
        errors.append(f"eastmoney:{type(exc).__name__}:{exc}")

    try:
        raw = ak.stock_zh_a_daily(
            symbol=_sina_code(symbol),
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust=adjust,
        )
        if raw is None or raw.empty:
            raise ProviderError("Sina upstream returned no rows")
        mapping = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
            "换手率": "turnover",
        }
        frame = normalize_ohlcv(raw.rename(columns=mapping))
        frame = frame[
            (frame["date"].dt.date >= start) & (frame["date"].dt.date <= end)
        ].reset_index(drop=True)
        if frame.empty:
            raise ProviderError("Sina fallback had no rows in requested range")
        return frame, "sina", errors
    except Exception as exc:  # noqa: BLE001 - third-party provider boundary
        errors.append(f"sina:{type(exc).__name__}:{exc}")
        raise ProviderError(
            "AKShare Eastmoney and Sina upstreams both failed: " + " | ".join(errors)
        ) from exc


def _crosscheck(
    left: pd.DataFrame,
    right: pd.DataFrame,
    tolerance: float,
) -> dict[str, object]:
    a = left[["date", "open", "high", "low", "close"]]
    b = right[["date", "open", "high", "low", "close"]]
    merged = a.merge(b, on="date", suffixes=("_a", "_b"))
    if merged.empty:
        return {
            "status": "NO_OVERLAP",
            "overlap_rows": 0,
            "max_relative_price_diff": None,
            "tolerance": tolerance,
        }
    max_diff = 0.0
    for field in ("open", "high", "low", "close"):
        x = merged[f"{field}_a"].astype(float)
        y = merged[f"{field}_b"].astype(float)
        denom = pd.concat([x.abs(), y.abs()], axis=1).max(axis=1).replace(0, np.nan)
        diff = ((x - y).abs() / denom).dropna()
        if not diff.empty:
            max_diff = max(max_diff, float(diff.max()))
    return {
        "status": "MATCH" if max_diff <= tolerance else "WARN",
        "overlap_rows": len(merged),
        "max_relative_price_diff": max_diff,
        "latest_common_date": str(pd.Timestamp(merged["date"].max()).date()),
        "tolerance": tolerance,
    }


def run_market_data_resilient(
    operation: ExecutionOperation,
    context: WorkerContext,
) -> OperationResult:
    parameters = operation.parameters
    symbol = _symbol(parameters)
    end = _as_of(parameters)
    history_days = max(30, min(int(parameters.get("history_days") or 450), 3650))
    start = end - timedelta(days=history_days)
    adjust = str(parameters.get("adjust") or "qfq")
    tolerance = float(parameters.get("price_tolerance") or 0.005)

    successes: list[tuple[str, str, pd.DataFrame]] = []
    provider_status: list[dict[str, object]] = []

    try:
        frame, upstream, prior_errors = _akshare_daily_resilient(symbol, start, end, adjust)
        successes.append(("akshare", upstream, frame))
        provider_status.append(
            {
                "provider": "akshare",
                "upstream": upstream,
                "status": "PASS",
                "rows": len(frame),
                "first_date": str(frame["date"].iloc[0].date()),
                "last_date": str(frame["date"].iloc[-1].date()),
                "fallback_errors": prior_errors,
            }
        )
    except Exception as exc:  # noqa: BLE001 - provider boundary
        provider_status.append(
            {
                "provider": "akshare",
                "status": "BLOCK",
                "error": f"{type(exc).__name__}:{exc}",
            }
        )

    try:
        frame = BaoStockProvider().get_daily_bars(symbol, start, end, adjust)
        successes.append(("baostock", "baostock", frame))
        provider_status.append(
            {
                "provider": "baostock",
                "upstream": "baostock",
                "status": "PASS",
                "rows": len(frame),
                "first_date": str(frame["date"].iloc[0].date()),
                "last_date": str(frame["date"].iloc[-1].date()),
            }
        )
    except Exception as exc:  # noqa: BLE001 - provider boundary
        provider_status.append(
            {
                "provider": "baostock",
                "status": "BLOCK",
                "error": f"{type(exc).__name__}:{exc}",
            }
        )

    if not successes:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=["ALL_MARKET_PROVIDERS_FAILED"],
            metrics={"provider_count": len(provider_status)},
            warnings=[json.dumps(provider_status, ensure_ascii=False)],
        )

    primary_name, primary_upstream, primary = successes[0]
    if len(successes) >= 2:
        crosscheck = _crosscheck(successes[0][2], successes[1][2], tolerance)
    else:
        crosscheck = {
            "status": "SINGLE_SOURCE",
            "overlap_rows": 0,
            "max_relative_price_diff": None,
            "tolerance": tolerance,
        }

    details = {
        "symbol": symbol,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "adjust": adjust,
        "primary_provider": primary_name,
        "primary_upstream": primary_upstream,
        "providers": provider_status,
        "crosscheck": crosscheck,
        "bars": json.loads(
            primary.to_json(orient="records", date_format="iso", force_ascii=False)
        ),
        "decision_authority": False,
    }
    context.frames[operation.operation_id] = primary
    context.payloads[operation.operation_id] = details
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, details)

    status = "PASS" if crosscheck["status"] == "MATCH" else "WARN"
    warnings = [] if status == "PASS" else [f"MARKET_{crosscheck['status']}"]
    if primary_name == "akshare" and primary_upstream != "eastmoney":
        warnings.append(f"AKSHARE_UPSTREAM_FALLBACK:{primary_upstream}")
        status = "WARN" if status == "PASS" else status
    return OperationResult(
        operation_id=operation.operation_id,
        status=status,
        exit_code=0,
        artifacts=[_artifact(path)],
        metrics={
            "rows": len(primary),
            "first_date": str(primary["date"].iloc[0].date()),
            "last_date": str(primary["date"].iloc[-1].date()),
            "crosscheck_status": crosscheck["status"],
            "provider_success_count": len(successes),
        },
        warnings=warnings,
    )
