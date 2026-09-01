from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from .contracts import ArtifactRef, ExecutionOperation, OperationResult
from .providers import AKShareResearchProvider
from .workers import WorkerContext


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _artifact(path: Path) -> ArtifactRef:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return ArtifactRef(
        path=path.name,
        sha256=digest,
        media_type="application/json",
        size_bytes=path.stat().st_size,
    )


def _subject(parameters: dict[str, object]) -> str:
    values = parameters.get("subject_ids") or []
    if not isinstance(values, list) or not values:
        raise ValueError("INDUSTRY_MACRO requires subject_ids")
    return str(values[0]).strip()


def _frame_returns(frame: pd.DataFrame) -> dict[str, float | None]:
    if frame.empty or "close" not in frame.columns:
        return {"20d": None, "60d": None, "120d": None}
    close = pd.to_numeric(frame["close"], errors="coerce").dropna()

    def value(window: int) -> float | None:
        if len(close) <= window:
            return None
        return float(close.iloc[-1] / close.iloc[-1 - window] - 1.0)

    return {"20d": value(20), "60d": value(60), "120d": value(120)}


def _infer_industry(profile: dict[str, object]) -> str | None:
    for key in ("所属行业", "行业", "industry", "证监会行业"):
        value = profile.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def run_industry_macro(
    operation: ExecutionOperation,
    context: WorkerContext,
) -> OperationResult:
    symbol = _subject(operation.parameters)
    as_of = pd.Timestamp(str(operation.parameters.get("as_of"))).date()
    history_days = max(120, min(int(operation.parameters.get("history_days") or 450), 3650))
    start = as_of - pd.Timedelta(days=history_days)
    start_date = pd.Timestamp(start).date()
    provider = AKShareResearchProvider()
    warnings: list[str] = []

    industry_name = operation.parameters.get("industry_name")
    profile: dict[str, object] | None = None
    if industry_name is None:
        try:
            profile = provider.get_company_profile(symbol)
            industry_name = _infer_industry(profile)
        except Exception as exc:
            warnings.append(f"INDUSTRY_PROFILE_UNAVAILABLE:{type(exc).__name__}:{exc}")
    industry_name = str(industry_name).strip() if industry_name else None

    benchmark_symbol = str(operation.parameters.get("benchmark_symbol") or "sh000300")
    benchmark_returns: dict[str, float | None] | None = None
    industry_returns: dict[str, float | None] | None = None
    constituents: list[dict[str, object]] = []

    try:
        benchmark = provider.get_index_daily(benchmark_symbol, start_date, as_of)
        benchmark_returns = _frame_returns(benchmark)
    except Exception as exc:
        warnings.append(f"BENCHMARK_UNAVAILABLE:{type(exc).__name__}:{exc}")

    if industry_name:
        try:
            industry = provider.get_industry_daily(industry_name, start_date, as_of)
            industry_returns = _frame_returns(industry)
        except Exception as exc:
            warnings.append(f"INDUSTRY_HISTORY_UNAVAILABLE:{type(exc).__name__}:{exc}")
        try:
            raw_constituents = provider.get_industry_constituents(industry_name)
            constituents = json.loads(
                raw_constituents.head(100).to_json(
                    orient="records", date_format="iso", force_ascii=False
                )
            )
        except Exception as exc:
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
            "industry_history_available": industry_returns is not None,
        },
        warnings=warnings,
        errors=errors,
    )
