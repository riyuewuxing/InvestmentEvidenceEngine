from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from .contracts import ArtifactRef, ExecutionOperation, OperationResult
from .providers import AKShareProvider, AKShareResearchProvider, BaoStockProvider, ProviderError, normalize_ohlcv
from .sources import DEFAULT_OFFICIAL_SOURCES, fetch_text


@dataclass
class WorkerContext:
    output_dir: Path
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    payloads: dict[str, dict[str, object]] = field(default_factory=dict)


def _jsonable_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    if frame.empty:
        return []
    return json.loads(frame.to_json(orient="records", date_format="iso", force_ascii=False))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path, *, media_type: str) -> ArtifactRef:
    return ArtifactRef(
        path=path.name,
        sha256=_sha256_file(path),
        media_type=media_type,
        size_bytes=path.stat().st_size,
    )


def _subject(parameters: dict[str, object]) -> str:
    values = parameters.get("subject_ids") or []
    if not isinstance(values, list) or not values:
        raise ValueError("operation requires subject_ids")
    subject = str(values[0]).strip()
    if not subject:
        raise ValueError("subject id must not be empty")
    return subject


def _as_of(parameters: dict[str, object]) -> date:
    value = parameters.get("as_of")
    if value is None:
        raise ValueError("operation requires as_of")
    return date.fromisoformat(str(value)[:10])


def _history_dates(parameters: dict[str, object]) -> tuple[date, date]:
    end = _as_of(parameters)
    history_days = int(parameters.get("history_days") or 450)
    history_days = max(30, min(history_days, 3650))
    return end - timedelta(days=history_days), end


def _fetch_market(
    parameters: dict[str, object],
) -> tuple[pd.DataFrame, dict[str, object], str]:
    symbol = _subject(parameters)
    start, end = _history_dates(parameters)
    adjust = str(parameters.get("adjust") or "qfq")
    providers = [AKShareProvider(), BaoStockProvider()]
    successes: list[tuple[str, pd.DataFrame]] = []
    provider_status: list[dict[str, object]] = []
    for provider in providers:
        try:
            frame = provider.get_daily_bars(symbol, start, end, adjust)
            successes.append((provider.name, frame))
            provider_status.append(
                {
                    "provider": provider.name,
                    "status": "PASS",
                    "rows": len(frame),
                    "first_date": str(frame["date"].iloc[0].date()),
                    "last_date": str(frame["date"].iloc[-1].date()),
                }
            )
        except Exception as exc:
            provider_status.append(
                {
                    "provider": provider.name,
                    "status": "BLOCK",
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )
    if not successes:
        raise ProviderError("all market providers failed")

    primary_name, primary = successes[0]
    crosscheck: dict[str, object] = {
        "status": "SINGLE_SOURCE",
        "overlap_rows": 0,
        "max_relative_price_diff": None,
    }
    if len(successes) >= 2:
        left = successes[0][1][["date", "open", "high", "low", "close"]]
        right = successes[1][1][["date", "open", "high", "low", "close"]]
        merged = left.merge(right, on="date", suffixes=("_a", "_b"))
        if merged.empty:
            crosscheck["status"] = "NO_OVERLAP"
        else:
            max_diff = 0.0
            for field_name in ("open", "high", "low", "close"):
                a = merged[f"{field_name}_a"].astype(float)
                b = merged[f"{field_name}_b"].astype(float)
                denom = pd.concat([a.abs(), b.abs()], axis=1).max(axis=1).replace(0, np.nan)
                rel = ((a - b).abs() / denom).dropna()
                if not rel.empty:
                    max_diff = max(max_diff, float(rel.max()))
            tolerance = float(parameters.get("price_tolerance") or 0.005)
            crosscheck = {
                "status": "MATCH" if max_diff <= tolerance else "WARN",
                "overlap_rows": len(merged),
                "max_relative_price_diff": max_diff,
                "latest_common_date": str(pd.Timestamp(merged["date"].max()).date()),
                "tolerance": tolerance,
            }
    details = {
        "symbol": symbol,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "adjust": adjust,
        "primary_provider": primary_name,
        "providers": provider_status,
        "crosscheck": crosscheck,
    }
    status = "PASS" if crosscheck["status"] == "MATCH" else "WARN"
    return primary, details, status


def run_market_data(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    frame, details, status = _fetch_market(operation.parameters)
    context.frames[operation.operation_id] = frame
    payload = {
        **details,
        "bars": _jsonable_records(frame),
        "decision_authority": False,
    }
    context.payloads[operation.operation_id] = payload
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    return OperationResult(
        operation_id=operation.operation_id,
        status=status,
        exit_code=0,
        artifacts=[_artifact(path, media_type="application/json")],
        metrics={
            "rows": len(frame),
            "first_date": str(frame["date"].iloc[0].date()),
            "last_date": str(frame["date"].iloc[-1].date()),
            "crosscheck_status": details["crosscheck"]["status"],
        },
        warnings=([] if status == "PASS" else [f"MARKET_{details['crosscheck']['status']}"]),
    )


def _dependency_frame(operation: ExecutionOperation, context: WorkerContext) -> pd.DataFrame | None:
    dependencies = operation.parameters.get("depends_on_operation_ids") or []
    if isinstance(dependencies, list):
        for dependency in dependencies:
            frame = context.frames.get(str(dependency))
            if frame is not None:
                return frame.copy()
    inline = operation.parameters.get("inline_ohlcv")
    if isinstance(inline, list) and inline:
        return normalize_ohlcv(pd.DataFrame(inline))
    return None


def _price_metrics(frame: pd.DataFrame) -> dict[str, object]:
    frame = normalize_ohlcv(frame)
    close = frame["close"].astype(float)
    volume = frame["volume"].astype(float)
    returns = close.pct_change()

    def horizon_return(window: int) -> float | None:
        if len(close) <= window:
            return None
        return float(close.iloc[-1] / close.iloc[-1 - window] - 1.0)

    def ma(window: int) -> float | None:
        if len(close) < window:
            return None
        return float(close.rolling(window).mean().iloc[-1])

    rolling_peak = close.cummax()
    drawdowns = close / rolling_peak - 1.0
    last_252 = close.tail(252)
    low_52 = float(last_252.min())
    high_52 = float(last_252.max())
    position_52w = None if math.isclose(high_52, low_52) else float((close.iloc[-1] - low_52) / (high_52 - low_52))

    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    prior_close = close.shift(1)
    true_range = pd.concat(
        [(high - low).abs(), (high - prior_close).abs(), (low - prior_close).abs()],
        axis=1,
    ).max(axis=1)
    downside = returns[returns < 0]
    volume_avg20 = float(volume.tail(20).mean()) if len(volume) >= 1 else 0.0
    return {
        "close": float(close.iloc[-1]),
        "return_5d": horizon_return(5),
        "return_20d": horizon_return(20),
        "return_60d": horizon_return(60),
        "return_120d": horizon_return(120),
        "return_250d": horizon_return(250),
        "moving_average": {f"ma{window}": ma(window) for window in (5, 10, 20, 60, 120, 250)},
        "realized_vol_20d": (
            float(returns.tail(20).std(ddof=1) * math.sqrt(252)) if returns.tail(20).count() >= 2 else None
        ),
        "downside_vol_20d": (
            float(downside.tail(20).std(ddof=1) * math.sqrt(252)) if downside.tail(20).count() >= 2 else None
        ),
        "atr14": float(true_range.tail(14).mean()) if not true_range.empty else None,
        "max_drawdown": float(drawdowns.min()),
        "drawdown_now": float(drawdowns.iloc[-1]),
        "position_52w": position_52w,
        "distance_to_52w_high": float(close.iloc[-1] / high_52 - 1.0) if high_52 else None,
        "volume_ratio_20d": float(volume.iloc[-1] / volume_avg20) if volume_avg20 else None,
        "rows": len(frame),
        "first_date": str(frame["date"].iloc[0].date()),
        "last_date": str(frame["date"].iloc[-1].date()),
    }


def run_price_analytics(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    frame = _dependency_frame(operation, context)
    warnings: list[str] = []
    if frame is None:
        frame, market_details, market_status = _fetch_market(operation.parameters)
        if market_status != "PASS":
            warnings.append(f"UPSTREAM_MARKET_{market_status}")
        warnings.append(f"IMPLICIT_MARKET_FETCH:{market_details['primary_provider']}")
    context.frames[operation.operation_id] = frame
    metrics = _price_metrics(frame)
    payload = {
        "symbol": _subject(operation.parameters),
        "as_of": _as_of(operation.parameters).isoformat(),
        "metrics": metrics,
        "warnings": warnings,
        "decision_authority": False,
    }
    context.payloads[operation.operation_id] = payload
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    return OperationResult(
        operation_id=operation.operation_id,
        status="WARN" if warnings else "PASS",
        exit_code=0,
        artifacts=[_artifact(path, media_type="application/json")],
        metrics=metrics,
        warnings=warnings,
    )


def run_kline_render(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    frame = _dependency_frame(operation, context)
    warnings: list[str] = []
    if frame is None:
        frame, details, status = _fetch_market(operation.parameters)
        warnings.append(f"IMPLICIT_MARKET_FETCH:{details['primary_provider']}")
        if status != "PASS":
            warnings.append(f"UPSTREAM_MARKET_{status}")
    frame = normalize_ohlcv(frame)
    context.frames[operation.operation_id] = frame
    png_path = context.output_dir / f"{operation.operation_id}.png"
    json_path = context.output_dir / f"{operation.operation_id}.json"
    renderer = "mplfinance"
    try:
        import mplfinance as mpf

        plot = frame[["date", "open", "high", "low", "close", "volume"]].copy()
        plot = plot.set_index("date")
        plot.columns = ["Open", "High", "Low", "Close", "Volume"]
        mav = tuple(window for window in (20, 60, 120) if len(plot) >= window)
        mpf.plot(
            plot.tail(260),
            type="candle",
            volume=True,
            mav=mav or None,
            savefig=str(png_path),
        )
    except Exception as exc:
        renderer = "matplotlib_fallback"
        warnings.append(f"MPLFINANCE_FALLBACK:{type(exc).__name__}")
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plot = frame.tail(260)
        figure, axes = plt.subplots(2, 1, sharex=True, figsize=(12, 7), height_ratios=[3, 1])
        axes[0].plot(plot["date"], plot["close"])
        for window in (20, 60, 120):
            if len(plot) >= window:
                axes[0].plot(plot["date"], plot["close"].rolling(window).mean(), label=f"MA{window}")
        axes[0].legend()
        axes[0].set_title(f"{_subject(operation.parameters)} price context")
        axes[1].bar(plot["date"], plot["volume"])
        figure.tight_layout()
        figure.savefig(png_path, dpi=140)
        plt.close(figure)

    sidecar = {
        "symbol": _subject(operation.parameters),
        "as_of": _as_of(operation.parameters).isoformat(),
        "renderer": renderer,
        "rows_rendered": min(260, len(frame)),
        "include_volume": True,
        "moving_averages": [window for window in (20, 60, 120) if len(frame) >= window],
        "event_markers_included": False,
        "source_operation_ids": operation.parameters.get("depends_on_operation_ids") or [],
        "warnings": warnings,
        "decision_authority": False,
    }
    _write_json(json_path, sidecar)
    context.payloads[operation.operation_id] = sidecar
    return OperationResult(
        operation_id=operation.operation_id,
        status="WARN" if warnings else "PASS",
        exit_code=0,
        artifacts=[
            _artifact(png_path, media_type="image/png"),
            _artifact(json_path, media_type="application/json"),
        ],
        metrics={"rows_rendered": sidecar["rows_rendered"], "renderer": renderer},
        warnings=warnings,
    )


def _event_category(title: str) -> str:
    text = title.casefold()
    rules = (
        ("BUYBACK", ("回购",)),
        ("DIVIDEND", ("分红", "派息", "权益分派")),
        ("EARNINGS", ("业绩", "年报", "季报", "半年报")),
        ("PLEDGE", ("质押",)),
        ("LOCKUP", ("解禁", "限售",)),
    )
    for category, tokens in rules:
        if any(token.casefold() in text for token in tokens):
            return category
    return "OTHER"


def run_company_event_timeline(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    symbol = _subject(operation.parameters)
    end = _as_of(operation.parameters)
    lookback_days = int(operation.parameters.get("lookback_days") or 365)
    start = end - timedelta(days=max(1, min(lookback_days, 3650)))
    provider = AKShareResearchProvider()
    raw = provider.get_disclosures(symbol, start, end)
    items: list[dict[str, object]] = []
    for row in raw.to_dict(orient="records"):
        title = str(row.get("公告标题") or row.get("title") or "").strip()
        published = row.get("公告时间") or row.get("published_at")
        url = row.get("公告链接") or row.get("url")
        items.append(
            {
                "title": title,
                "category": _event_category(title),
                "published_at": str(published) if published is not None else None,
                "source_url": str(url) if url is not None else None,
                "provider": "akshare_cninfo",
            }
        )
    payload = {
        "symbol": symbol,
        "start": start.isoformat(),
        "as_of": end.isoformat(),
        "events": items,
        "event_count": len(items),
        "source_priority": "official_disclosure_metadata",
        "decision_authority": False,
    }
    context.payloads[operation.operation_id] = payload
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    return OperationResult(
        operation_id=operation.operation_id,
        status="PASS",
        exit_code=0,
        artifacts=[_artifact(path, media_type="application/json")],
        metrics={"event_count": len(items)},
    )


def run_fundamental_history(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    symbol = _subject(operation.parameters)
    as_of = _as_of(operation.parameters)
    provider = AKShareResearchProvider()
    warnings: list[str] = []
    profile: dict[str, object] | None = None
    indicators: list[dict[str, object]] = []
    statements: dict[str, list[dict[str, object]]] = {}
    try:
        profile = provider.get_company_profile(symbol)
    except Exception as exc:
        warnings.append(f"PROFILE_UNAVAILABLE:{type(exc).__name__}:{exc}")
    try:
        frame = provider.get_financial_indicators(symbol, max(1990, as_of.year - 6))
        indicators = _jsonable_records(frame)
    except Exception as exc:
        warnings.append(f"INDICATORS_UNAVAILABLE:{type(exc).__name__}:{exc}")
    try:
        statement_frames = provider.get_financial_statements(symbol)
        statements = {key: _jsonable_records(value) for key, value in statement_frames.items()}
    except Exception as exc:
        warnings.append(f"STATEMENTS_UNAVAILABLE:{type(exc).__name__}:{exc}")
    if profile is None and not indicators and not statements:
        raise ProviderError("all fundamental sources failed")
    warnings.append("PIT_AVAILABILITY_DATES_REQUIRE_SEPARATE_VALIDATION")
    payload = {
        "symbol": symbol,
        "as_of": as_of.isoformat(),
        "company_profile": profile,
        "financial_indicators": indicators,
        "statements": statements,
        "pit_safe": False,
        "warnings": warnings,
        "decision_authority": False,
    }
    context.payloads[operation.operation_id] = payload
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    return OperationResult(
        operation_id=operation.operation_id,
        status="WARN",
        exit_code=0,
        artifacts=[_artifact(path, media_type="application/json")],
        metrics={
            "indicator_rows": len(indicators),
            "statement_types": len(statements),
        },
        warnings=warnings,
    )


def run_valuation_history(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    symbol = _subject(operation.parameters)
    provider = AKShareResearchProvider()
    frame = provider.get_valuation_history(symbol)
    payload = {
        "symbol": symbol,
        "as_of": _as_of(operation.parameters).isoformat(),
        "records": _jsonable_records(frame),
        "rows": len(frame),
        "decision_authority": False,
    }
    context.payloads[operation.operation_id] = payload
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    return OperationResult(
        operation_id=operation.operation_id,
        status="PASS",
        exit_code=0,
        artifacts=[_artifact(path, media_type="application/json")],
        metrics={"rows": len(frame)},
    )


def run_official_source(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    requested = operation.parameters.get("source_ids")
    source_ids = (
        [str(item) for item in requested]
        if isinstance(requested, list) and requested
        else list(DEFAULT_OFFICIAL_SOURCES)
    )
    checks: list[dict[str, object]] = []
    status = "PASS"
    for source_id in source_ids:
        spec = DEFAULT_OFFICIAL_SOURCES.get(source_id)
        if spec is None:
            checks.append({"source_id": source_id, "status": "BLOCK", "error": "UNKNOWN_SOURCE_ID"})
            status = "BLOCK"
            continue
        try:
            text = fetch_text(spec.url)
            missing = [token for token in spec.expected_tokens if token not in text]
            source_status = "PASS" if not missing else "BLOCK"
            if source_status == "BLOCK":
                status = "BLOCK"
            checks.append(
                {
                    "source_id": source_id,
                    "status": source_status,
                    "url": spec.url,
                    "expected_tokens": list(spec.expected_tokens),
                    "missing_tokens": missing,
                    "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                }
            )
        except Exception as exc:
            checks.append(
                {
                    "source_id": source_id,
                    "status": "BLOCK",
                    "url": spec.url,
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )
            status = "BLOCK"
    payload = {
        "as_of": _as_of(operation.parameters).isoformat(),
        "checks": checks,
        "decision_authority": False,
    }
    context.payloads[operation.operation_id] = payload
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    return OperationResult(
        operation_id=operation.operation_id,
        status=status,
        exit_code=0 if status != "BLOCK" else 2,
        artifacts=[_artifact(path, media_type="application/json")],
        metrics={"source_count": len(checks)},
        errors=[item.get("error", "") for item in checks if item.get("status") == "BLOCK" and item.get("error")],
    )


Worker = Callable[[ExecutionOperation, WorkerContext], OperationResult]

WORKERS: dict[str, Worker] = {
    "MARKET_DATA": run_market_data,
    "PRICE_ANALYTICS": run_price_analytics,
    "KLINE_RENDER": run_kline_render,
    "COMPANY_EVENT_TIMELINE": run_company_event_timeline,
    "FUNDAMENTAL_HISTORY": run_fundamental_history,
    "VALUATION_HISTORY": run_valuation_history,
    "OFFICIAL_SOURCE": run_official_source,
}


def run_operation(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    worker = WORKERS.get(operation.kind)
    if worker is None:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=[f"UNIMPLEMENTED_OPERATION:{operation.kind}"],
        )
    try:
        return worker(operation, context)
    except Exception as exc:
        return OperationResult(
            operation_id=operation.operation_id,
            status="ERROR",
            exit_code=1,
            errors=[f"{type(exc).__name__}:{exc}"],
        )
