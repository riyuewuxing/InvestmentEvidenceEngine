from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .akshare_daily_adapter import call_akshare_daily, call_sina_stock_daily
from .bounded_worker import run_json_worker, write_worker_result
from .contracts import ArtifactRef, ExecutionOperation, OperationResult
from .evidence_time_guard import SHANGHAI, aware, validate_event_cutoff
from .providers import BaoStockProvider, ProviderError, normalize_ohlcv
from .table_wire import pack_frame, unpack_frame
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
    values = parameters.get("subject_ids")
    if (not isinstance(values, list) or len(values) != 1
            or not isinstance(values[0], str) or re.fullmatch(r"[0-9]{6}", values[0]) is None):
        raise ValueError("MARKET_DATA_REQUIRES_ONE_EXACT_SYMBOL")
    return values[0]


def _window(parameters: dict[str, object], context: WorkerContext) -> tuple[date, date, int]:
    raw = parameters.get("as_of")
    if not isinstance(raw, str) or (context.request_as_of is not None and raw != context.request_as_of):
        raise ValueError("MARKET_AS_OF_MISSING_OR_MISMATCH")
    cutoff, day_scope = validate_event_cutoff(raw)
    now = context.clock()
    if cutoff is None or not aware(now):
        raise ValueError("MARKET_AWARE_CLOCK_REQUIRED")
    now = now.astimezone(SHANGHAI)
    local = cutoff if day_scope else cutoff.astimezone(SHANGHAI)
    if local.date() > now.date() or (not day_scope and local > now):
        raise ValueError("MARKET_FUTURE_CUTOFF")
    days = parameters.get("history_days", 450)
    offset = parameters.get("history_end_offset_days", 0)
    if type(days) is not int or not 30 <= days <= 3650:
        raise ValueError("MARKET_HISTORY_DAYS_OUT_OF_RANGE")
    if type(offset) is not int or not 0 <= offset <= 30:
        raise ValueError("MARKET_HISTORY_OFFSET_OUT_OF_RANGE")
    end = local.date() - timedelta(days=offset)
    # A date-only historical scope is not an intraday availability claim.
    # Today's unfinished daily bar and precise pre-close cutoffs are excluded.
    effective = now if day_scope and local.date() == now.date() else local
    if (not day_scope or local.date() == now.date()) and effective.time() < time(15, 30):
        end = min(end, local.date() - timedelta(days=1))
    return end - timedelta(days=days), end, offset


def _sina_code(symbol: str) -> str:
    if len(symbol) != 6 or not symbol.isdigit():
        raise ProviderError(f"unsupported A-share symbol: {symbol}")
    if symbol.startswith(("5", "6", "9")):
        return f"sh{symbol}"
    if symbol.startswith(("0", "1", "2", "3")):
        return f"sz{symbol}"
    raise ProviderError(f"Sina fallback cannot infer exchange for {symbol}")


def _bounded_frame(frame: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    frame = normalize_ohlcv(frame, strict=True)
    if not frame["date"].dt.date.between(start, end).all():
        raise ProviderError("MARKET_PROVIDER_RETURNED_OUTSIDE_REQUEST_WINDOW")
    return frame


def _child(source: str, symbol: str, start: date, end: date, adjust: str, path: Path) -> None:
    if source == "baostock":
        frame = BaoStockProvider().get_daily_bars(symbol, start, end, adjust, strict=True)
    else:
        import akshare as ak

        kwargs = dict(symbol=symbol if source == "eastmoney" else _sina_code(symbol),
                      start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"),
                      adjust=adjust)
        if source == "eastmoney":
            raw = call_akshare_daily(ak, period="daily", **kwargs)
        elif source == "sina":
            raw = call_sina_stock_daily(ak, **kwargs)
        else:
            raise ValueError("unknown provider")
        if raw is None or raw.empty:
            raise ProviderError("MARKET_PROVIDER_EMPTY")
        frame = raw.rename(columns={
            "日期": "date", "开盘": "open", "最高": "high", "最低": "low", "收盘": "close",
            "成交量": "volume", "成交额": "amount", "换手率": "turnover",
        })
    frame = _bounded_frame(frame, start, end)
    write_worker_result(path, {"source": source, "symbol": symbol, "start": start.isoformat(),
                               "end": end.isoformat(), "adjust": adjust,
                               "retrieved_at": datetime.now(UTC).isoformat(),
                               "frame": pack_frame(frame)})


def _observe(source: str, symbol: str, start: date, end: date, adjust: str):
    if source == "tencent":
        # Lazy import avoids a circular import; the direct adapter observes
        # raw day bars and rehashes the actual HTTP body in the parent.
        from .retrospective_control import acquire_tencent

        if adjust != "":
            raise ValueError("TENCENT_RAW_ONLY")
        frame, info = acquire_tencent(symbol, start, end)
        return frame, info | {"upstream": "tencent", "volume_unit_verified": False}
    result = run_json_worker(
        (sys.executable, "-m", "investment_evidence_engine.market_worker", "--child",
         source, symbol, start.isoformat(), end.isoformat(), adjust or "none"),
        timeout_seconds=30,
    )
    info = {"provider": "baostock" if source == "baostock" else "akshare",
            "upstream": source, "status": "BLOCK", "worker_status": result.status,
            "elapsed_seconds": result.elapsed_seconds}
    if result.status != "OK" or result.payload is None:
        return None, info
    p = result.payload
    try:
        if (p["source"], p["symbol"], p["start"], p["end"], p["adjust"]) != (
                source, symbol, start.isoformat(), end.isoformat(), adjust):
            raise ValueError("MARKET_WORKER_IDENTITY_MISMATCH")
        retrieved = datetime.fromisoformat(p["retrieved_at"])
        if not aware(retrieved) or retrieved > datetime.now(UTC):
            raise ValueError("MARKET_WORKER_INVALID_RETRIEVAL_TIME")
        frame = _bounded_frame(unpack_frame(p["frame"]), start, end)
    except (ValueError, TypeError, KeyError, AttributeError, ProviderError) as exc:
        return None, {**info, "worker_status": "PAYLOAD_INVALID", "error_type": type(exc).__name__}
    return frame, {**info, "status": "OBSERVED", "retrieved_at": retrieved.isoformat(),
                   "rows": len(frame), "first_date": str(frame["date"].iloc[0].date()),
                   "last_date": str(frame["date"].iloc[-1].date())}


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
        "status": ("PRICE_CONFLICT" if max_diff > tolerance else "DATE_COVERAGE_MISMATCH"
                   if set(a["date"]) != set(b["date"]) else "MATCH_OBSERVED_ROWS"),
        "left_only_dates": len(set(a["date"]) - set(b["date"])),
        "right_only_dates": len(set(b["date"]) - set(a["date"])),
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
    try:
        symbol = _symbol(parameters)
        start, end, offset = _window(parameters, context)
        adjust = parameters.get("adjust", "qfq")
        if adjust == "none":
            adjust = ""
        if not isinstance(adjust, str) or adjust not in {"", "qfq", "hfq"}:
            raise ValueError("MARKET_ADJUST_INVALID")
        tolerance = parameters.get("price_tolerance", 0.005)
        if (type(tolerance) not in {int, float} or not math.isfinite(tolerance)
                or not 0 <= tolerance <= 0.1):
            raise ValueError("MARKET_TOLERANCE_INVALID")
        if "input_artifact_ids" in parameters:
            ids = parameters["input_artifact_ids"]
            if (not isinstance(ids, list) or len(ids) != 1 or not isinstance(ids[0], str)
                    or ids[0] not in context.input_artifacts):
                raise ValueError("MARKET_INPUT_ARTIFACT_NOT_OBSERVED")
            ref = context.input_artifacts[ids[0]]
            if ref.selector.value != symbol or ref.as_of != parameters["as_of"]:
                raise ValueError("MARKET_INPUT_ARTIFACT_SCOPE_MISMATCH")
    except (ValueError, TypeError, OverflowError) as exc:
        return OperationResult(operation_id=operation.operation_id, status="BLOCK",
                               exit_code=2, errors=[str(exc)])

    successes: list[tuple[str, str, pd.DataFrame]] = []
    provider_status: list[dict[str, object]] = []
    def attempt(source: str) -> None:
        frame, info = _observe(source, symbol, start, end, adjust)
        provider_status.append(info)
        if frame is not None:
            successes.append((str(info["provider"]), source, frame))

    # Tencent raw OHLC is a second observation only: its volume units have
    # not been independently established, so never substitute it as the
    # generic primary OHLCV feed. Do not compare its raw bars to qfq/hfq.
    tencent_eligible = (adjust == "" and (end - start).days <= 1100
                        and symbol.startswith(("60", "68", "00", "30")))
    attempt("eastmoney")
    if not successes:
        attempt("sina")
    if successes and tencent_eligible:
        attempt("tencent")
    if len(successes) < 2:
        attempt("baostock")
    if tencent_eligible and len(successes) == 1 and successes[0][1] == "baostock":
        attempt("tencent")

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
        "as_of": parameters["as_of"],
        "history_end_offset_days": offset,
        "pit_safe": False,
        "historical_vintage_verified": False,
        "source_independence_verified": False,
        "raw_provider_bytes_retained": False,
        "primary_provider": primary_name,
        "primary_upstream": primary_upstream,
        "providers": provider_status,
        "crosscheck": crosscheck,
        "crosscheck_fields": ["open", "high", "low", "close"],
        "volume_units_crosschecked": False,
        "bars": json.loads(
            primary.to_json(orient="records", date_format="iso", force_ascii=False)
        ),
        "decision_authority": False,
    }
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, details)
    if crosscheck["status"] in {"PRICE_CONFLICT", "NO_OVERLAP"}:
        return OperationResult(
            operation_id=operation.operation_id, status="BLOCK", exit_code=2,
            artifacts=[_artifact(path)], errors=[f"MARKET_{crosscheck['status']}"],
            metrics={"rows": len(primary), "crosscheck_status": crosscheck["status"],
                     "provider_success_count": len(successes)},
        )
    context.frames[operation.operation_id] = primary
    context.payloads[operation.operation_id] = details

    # Agreement of normalized rows is not proof of historical publication or vintage.
    status = "WARN"
    warnings = ["MARKET_HISTORICAL_VINTAGE_UNVERIFIED", "MARKET_SOURCE_INDEPENDENCE_UNVERIFIED"]
    if crosscheck["status"] != "MATCH_OBSERVED_ROWS":
        warnings.append(f"MARKET_{crosscheck['status']}")
    if primary_name == "akshare" and primary_upstream != "eastmoney":
        warnings.append(f"AKSHARE_UPSTREAM_FALLBACK:{primary_upstream}")
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


if __name__ == "__main__":
    if len(sys.argv) != 8 or sys.argv[1] != "--child":
        raise SystemExit(2)
    _child(sys.argv[2], sys.argv[3], date.fromisoformat(sys.argv[4]),
           date.fromisoformat(sys.argv[5]), "" if sys.argv[6] == "none" else sys.argv[6],
           Path(sys.argv[7]))
