from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .contracts import ArtifactRef, ExecutionOperation, OperationResult
from .providers import ProviderError
from .workers import WorkerContext, run_fundamental_history


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(path: Path) -> ArtifactRef:
    return ArtifactRef(
        path=path.name,
        sha256=_sha256(path),
        media_type="application/json",
        size_bytes=path.stat().st_size,
    )


def _subject(operation: ExecutionOperation) -> str:
    values = operation.parameters.get("subject_ids") or []
    if not isinstance(values, list) or not values:
        raise ValueError("FUNDAMENTAL_HISTORY requires subject_ids")
    return str(values[0]).zfill(6)


def _as_of(operation: ExecutionOperation) -> date:
    return date.fromisoformat(str(operation.parameters.get("as_of"))[:10])


def _ts_code(symbol: str) -> str:
    clean = symbol.lower().replace("sh.", "").replace("sz.", "").replace("bj.", "")
    if len(clean) != 6 or not clean.isdigit():
        raise ValueError(f"unsupported A-share symbol: {symbol}")
    if clean.startswith(("5", "6", "9")):
        return f"{clean}.SH"
    if clean.startswith(("0", "1", "2", "3")):
        return f"{clean}.SZ"
    if clean.startswith(("4", "8")):
        return f"{clean}.BJ"
    raise ValueError(f"cannot infer exchange for {symbol}")


def _pit_records(frame: pd.DataFrame, *, endpoint: str, as_of: date) -> list[dict[str, object]]:
    if frame is None or frame.empty:
        return []
    out = frame.copy()
    available_source = None
    for candidate in ("f_ann_date", "ann_date"):
        if candidate in out.columns:
            available_source = candidate
            break
    if available_source is None:
        raise ProviderError(f"{endpoint} has no announcement availability field")
    parsed = pd.to_datetime(out[available_source].astype(str), format="%Y%m%d", errors="coerce")
    # Date-only publication timestamps are conservatively treated as available next calendar day.
    out["available_at"] = parsed + pd.Timedelta(days=1)
    cutoff = pd.Timestamp(as_of)
    out = out[out["available_at"].notna() & (out["available_at"] <= cutoff)].copy()
    out["endpoint"] = endpoint
    return json.loads(out.to_json(orient="records", date_format="iso", force_ascii=False))


def _run_tushare_pit(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if not token:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=["PIT_FINANCIAL_SOURCE_UNAVAILABLE:TUSHARE_TOKEN_NOT_CONFIGURED"],
        )
    try:
        import tushare as ts
    except ImportError:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=["PIT_FINANCIAL_SOURCE_UNAVAILABLE:TUSHARE_NOT_INSTALLED"],
        )

    symbol = _subject(operation)
    cutoff = _as_of(operation)
    start = cutoff - timedelta(days=365 * 6 + 2)
    pro = ts.pro_api(token)
    ts_code = _ts_code(symbol)
    attempts: list[dict[str, object]] = []
    records: dict[str, list[dict[str, object]]] = {}
    warnings: list[str] = []
    for endpoint in ("income", "balancesheet", "cashflow", "fina_indicator"):
        try:
            method = getattr(pro, endpoint)
            frame = method(
                ts_code=ts_code,
                start_date=start.strftime("%Y%m%d"),
                end_date=cutoff.strftime("%Y%m%d"),
            )
            endpoint_records = _pit_records(frame, endpoint=endpoint, as_of=cutoff)
            records[endpoint] = endpoint_records
            attempts.append({"endpoint": endpoint, "status": "PASS", "rows": len(endpoint_records)})
        except Exception as exc:
            attempts.append(
                {"endpoint": endpoint, "status": "WARN", "error": f"{type(exc).__name__}:{exc}"}
            )
            warnings.append(f"{endpoint.upper()}_UNAVAILABLE")
            records[endpoint] = []

    total_rows = sum(len(items) for items in records.values())
    if total_rows == 0:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            metrics={"pit_safe": False, "rows": 0},
            warnings=warnings,
            errors=["PIT_FINANCIAL_SOURCE_RETURNED_NO_ADMISSIBLE_RECORDS"],
        )

    payload = {
        "symbol": symbol,
        "as_of": cutoff.isoformat(),
        "provider": "tushare",
        "availability_policy": "f_ann_date_else_ann_date_plus_one_calendar_day",
        "pit_safe": True,
        "records": records,
        "attempts": attempts,
        "warnings": warnings,
        "decision_authority": False,
    }
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    context.payloads[operation.operation_id] = payload
    return OperationResult(
        operation_id=operation.operation_id,
        status="WARN" if warnings else "PASS",
        exit_code=0,
        artifacts=[_artifact(path)],
        metrics={"pit_safe": True, "rows": total_rows, "provider": "tushare"},
        warnings=warnings,
    )


def run_fundamental_with_pit_guard(
    operation: ExecutionOperation,
    context: WorkerContext,
) -> OperationResult:
    cutoff = _as_of(operation)
    today = date.today()
    if cutoff > today:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=["FUTURE_AS_OF_NOT_ALLOWED"],
        )
    pit_required = bool(operation.parameters.get("pit_required", True))
    if pit_required and cutoff < today:
        return _run_tushare_pit(operation, context)
    # For a current snapshot, use public live sources; the base worker explicitly marks its
    # statement availability limitation as WARN rather than pretending historical PIT safety.
    return run_fundamental_history(operation, context)
