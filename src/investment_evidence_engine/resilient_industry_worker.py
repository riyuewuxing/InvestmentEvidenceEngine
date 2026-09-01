from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from .contracts import ArtifactRef, ExecutionOperation, OperationResult
from .industry_worker import _frame_returns, _infer_industry
from .providers import AKShareResearchProvider, ProviderError, normalize_ohlcv
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


def _subject(parameters: dict[str, object]) -> str:
    values = parameters.get("subject_ids") or []
    if not isinstance(values, list) or not values:
        raise ValueError("INDUSTRY_MACRO requires subject_ids")
    return str(values[0]).strip().zfill(6)


def _sina_index(index_symbol: str, start, end) -> pd.DataFrame:
    try:
        import akshare as ak
    except ImportError as exc:
        raise ProviderError("akshare is not installed") from exc
    raw = ak.stock_zh_index_daily(symbol=index_symbol)
    if raw is None or raw.empty:
        raise ProviderError(f"Sina index fallback returned no rows for {index_symbol}")
    mapping = {
        "日期": "date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
    }
    frame = normalize_ohlcv(raw.rename(columns=mapping))
    frame = frame[(frame["date"].dt.date >= start) & (frame["date"].dt.date <= end)].reset_index(drop=True)
    if frame.empty:
        raise ProviderError("Sina index fallback had no rows in requested range")
    return frame


def run_industry_macro_resilient(
    operation: ExecutionOperation,
    context: WorkerContext,
) -> OperationResult:
    symbol = _subject(operation.parameters)
    as_of = pd.Timestamp(str(operation.parameters.get("as_of"))).date()
    history_days = max(120, min(int(operation.parameters.get("history_days") or 450), 3650))
    start_date = (pd.Timestamp(as_of) - pd.Timedelta(days=history_days)).date()
    provider = AKShareResearchProvider()
    warnings: list[str] = []

    industry_name = operation.parameters.get("industry_name")
    profile: dict[str, object] | None = None
    if industry_name is None:
        try:
            profile = provider.get_company_profile(symbol)
            industry_name = _infer_industry(profile)
        except Exception as exc:  # noqa: BLE001 - external provider boundary
            warnings.append(f"INDUSTRY_PROFILE_UNAVAILABLE:{type(exc).__name__}:{exc}")
    industry_name = str(industry_name).strip() if industry_name else None

    benchmark_symbol = str(operation.parameters.get("benchmark_symbol") or "sh000300")
    benchmark_returns: dict[str, float | None] | None = None
    benchmark_upstream: str | None = None
    industry_returns: dict[str, float | None] | None = None
    constituents: list[dict[str, object]] = []

    try:
        benchmark = provider.get_index_daily(benchmark_symbol, start_date, as_of)
        benchmark_returns = _frame_returns(benchmark)
        benchmark_upstream = "eastmoney"
    except Exception as primary_exc:  # noqa: BLE001 - external provider boundary
        warnings.append(f"BENCHMARK_PRIMARY_UNAVAILABLE:{type(primary_exc).__name__}:{primary_exc}")
        try:
            benchmark = _sina_index(benchmark_symbol, start_date, as_of)
            benchmark_returns = _frame_returns(benchmark)
            benchmark_upstream = "sina"
            warnings.append("BENCHMARK_FALLBACK:SINA")
        except Exception as fallback_exc:  # noqa: BLE001 - external provider boundary
            warnings.append(f"BENCHMARK_FALLBACK_UNAVAILABLE:{type(fallback_exc).__name__}:{fallback_exc}")

    if industry_name:
        try:
            industry = provider.get_industry_daily(industry_name, start_date, as_of)
            industry_returns = _frame_returns(industry)
        except Exception as exc:  # noqa: BLE001 - external provider boundary
            warnings.append(f"INDUSTRY_HISTORY_UNAVAILABLE:{type(exc).__name__}:{exc}")
        try:
            raw_constituents = provider.get_industry_constituents(industry_name)
            constituents = json.loads(
                raw_constituents.head(100).to_json(
                    orient="records", date_format="iso", force_ascii=False
                )
            )
        except Exception as exc:  # noqa: BLE001 - external provider boundary
            warnings.append(f"INDUSTRY_CONSTITUENTS_UNAVAILABLE:{type(exc).__name__}:{exc}")
    else:
        warnings.append("INDUSTRY_NAME_UNKNOWN")

    if benchmark_returns is None and industry_returns is None and not constituents:
        status = "BLOCK"
        errors = ["NO_INDUSTRY_OR_BENCHMARK_CONTEXT"]
    else:
        status = "WARN" if warnings else "PASS"
        errors = []

    payload = {
        "symbol": symbol,
        "as_of": as_of.isoformat(),
        "industry_name": industry_name,
        "company_profile": profile,
        "benchmark_symbol": benchmark_symbol,
        "benchmark_upstream": benchmark_upstream,
        "benchmark_returns": benchmark_returns,
        "industry_returns": industry_returns,
        "constituents": constituents,
        "constituent_count": len(constituents),
        "warnings": warnings,
        "decision_authority": False,
    }
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    context.payloads[operation.operation_id] = payload
    return OperationResult(
        operation_id=operation.operation_id,
        status=status,
        exit_code=0 if status != "BLOCK" else 2,
        artifacts=[_artifact(path)],
        metrics={
            "industry_name": industry_name,
            "constituent_count": len(constituents),
            "benchmark_available": benchmark_returns is not None,
            "benchmark_upstream": benchmark_upstream,
            "industry_history_available": industry_returns is not None,
        },
        warnings=warnings,
        errors=errors,
    )
