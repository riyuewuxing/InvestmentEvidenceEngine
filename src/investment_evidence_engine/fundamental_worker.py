from __future__ import annotations

import json
import os
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .contracts import ArtifactRef, ExecutionOperation, OperationResult
from .evidence_time_guard import validate_event_cutoff
from .providers import ProviderError
from .vendor_financial_scope import consolidated_basis, financial_date_scope
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
    values = operation.parameters.get("subject_ids")
    if (not isinstance(values, list) or len(values) != 1
            or not isinstance(values[0], str) or re.fullmatch(r"[0-9]{6}", values[0]) is None):
        raise ValueError("FUNDAMENTAL_ONE_EXACT_STOCK_SYMBOL_REQUIRED")
    _ts_code(values[0])
    return values[0]


def _as_of(operation: ExecutionOperation) -> date:
    raw = operation.parameters.get("as_of")
    if not isinstance(raw, str):
        raise ValueError("FUNDAMENTAL_EXACT_DATE_REQUIRED")
    parsed = date.fromisoformat(raw)
    if raw != parsed.isoformat():
        raise ValueError("FUNDAMENTAL_EXACT_DATE_REQUIRED")
    return parsed


def _ts_code(symbol: str) -> str:
    if not isinstance(symbol, str) or re.fullmatch(r"[0-9]{6}", symbol) is None:
        raise ValueError("FUNDAMENTAL_SYMBOL_INVALID")
    if symbol.startswith(("60", "68")):
        return f"{symbol}.SH"
    if symbol.startswith(("00", "30")):
        return f"{symbol}.SZ"
    if symbol.startswith(("4", "8", "92")):
        return f"{symbol}.BJ"
    raise ValueError("FUNDAMENTAL_UNSUPPORTED_STOCK_IDENTITY")


def _pit_records(frame: pd.DataFrame, *, endpoint: str, as_of: date,
                 expected_code: str | None = None) -> list[dict[str, object]]:
    """Conservative vendor label filter only; not original-version selection."""
    if frame is None or frame.empty:
        return []
    if not frame.columns.is_unique or "end_date" not in frame:
        raise ProviderError("FUNDAMENTAL_VENDOR_SCHEMA")
    if expected_code is not None and ("ts_code" not in frame
            or any(not isinstance(v, str) or v != expected_code for v in frame["ts_code"])):
        raise ProviderError("FUNDAMENTAL_VENDOR_SUBJECT_MISMATCH")
    # Serialize once, preserving nulls, and validate the explicit vendor date
    # and report type. No historical availability timestamps are manufactured.
    rows = json.loads(frame.to_json(orient="records", date_format="iso", force_ascii=False))
    eligible = []
    for row in rows:
        scope = financial_date_scope(row.get("end_date"), row.get("ann_date"), row.get("f_ann_date"))
        basis = ("INDICATOR_BASIS_UNVERIFIED" if endpoint == "fina_indicator"
                 else consolidated_basis(row.get("report_type"), allow_unspecified=expected_code is None))
        available_proxy = date.fromisoformat(scope["declared_date_ceiling"]) + timedelta(days=1)
        if available_proxy > as_of:
            continue
        for clock in ("available_at", "published_at", "retrieved_at", "observed_at",
                      "ingested_at", "admitted_at", "durable_verified_at", "effective_at"):
            row.pop(clock, None)
        row.update(endpoint=endpoint, vendor_date_filter_proxy=available_proxy.isoformat(),
                   vendor_date_scope=scope, report_basis=basis,
                   historical_vintage_verified=False, pit_safe=False)
        eligible.append(row)
    return eligible


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
            basis_filter = {"report_type": "1"} if endpoint != "fina_indicator" else {}
            frame = method(
                ts_code=ts_code,
                start_date=start.strftime("%Y%m%d"),
                end_date=cutoff.strftime("%Y%m%d"),
                **basis_filter,
            )
            endpoint_records = _pit_records(frame, endpoint=endpoint, as_of=cutoff, expected_code=ts_code)
            records[endpoint] = endpoint_records
            attempts.append({"endpoint": endpoint, "status": "PASS", "rows": len(endpoint_records)})
        except Exception as exc:
            attempts.append(
                {"endpoint": endpoint, "status": "WARN", "error": type(exc).__name__}
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

    warnings.append("VENDOR_ANNOUNCEMENT_DATE_NOT_VERIFIED_HISTORICAL_VINTAGE")
    payload = {
        "symbol": symbol,
        "as_of": cutoff.isoformat(),
        "provider": "tushare",
        "availability_policy": "later_of_valid_vendor_notice_days_plus_one_calendar_day_filter_only",
        "report_basis": "LATEST_CONSOLIDATED_VENDOR_ROW_NOT_ORIGINAL_VINTAGE",
        "observed_at": datetime.now(UTC).isoformat(),
        "pit_safe": False,
        "historical_vintage_verified": False,
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
        status="BLOCK",
        exit_code=2,
        artifacts=[_artifact(path)],
        metrics={"pit_safe": False, "rows": total_rows, "provider": "tushare"},
        warnings=warnings,
        errors=["FUNDAMENTAL_HISTORICAL_VINTAGE_NOT_VERIFIED"],
    )


def run_fundamental_with_pit_guard(
    operation: ExecutionOperation,
    context: WorkerContext,
) -> OperationResult:
    def blocked(reason: str) -> OperationResult:
        return OperationResult(operation_id=operation.operation_id, status="BLOCK",
                               exit_code=2, errors=[reason])

    try:
        _subject(operation)
        cutoff = _as_of(operation)
        if context.request_as_of is not None:
            ceiling, day_scope = validate_event_cutoff(context.request_as_of)
            if ceiling is None or not day_scope or cutoff > ceiling.date():
                return blocked("FUNDAMENTAL_REQUEST_SCOPE_EXCEEDED_OR_INSTANT_UNSUPPORTED")
    except (ValueError, TypeError, OverflowError):
        return blocked("FUNDAMENTAL_INVALID_SUBJECT_OR_CUTOFF")
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if cutoff > today:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=["FUTURE_AS_OF_NOT_ALLOWED"],
        )
    pit_required = operation.parameters.get("pit_required", True)
    if type(pit_required) is not bool:
        raise ValueError("FUNDAMENTAL_PIT_REQUIRED_MUST_BE_BOOLEAN")
    if cutoff < today:
        if not pit_required:
            return blocked("FUNDAMENTAL_LIVE_SNAPSHOT_CANNOT_ANSWER_HISTORICAL_CUTOFF")
        return _run_tushare_pit(operation, context)
    # For a current snapshot, use public live sources; the base worker explicitly marks its
    # statement availability limitation as WARN rather than pretending historical PIT safety.
    result = run_fundamental_history(operation, context)
    if pit_required:
        result.status = "BLOCK"
        result.exit_code = 2
        result.metrics["pit_safe"] = False
        result.errors.append("FUNDAMENTAL_CURRENT_AVAILABILITY_NOT_VERIFIED")
    return result
