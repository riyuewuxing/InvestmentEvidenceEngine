from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .contracts import ArtifactRef, ExecutionOperation, InputArtifactRef, OperationResult, canonical_sha256
from .providers import AKShareProvider, AKShareResearchProvider, BaoStockProvider, ProviderError, normalize_ohlcv
from .sources import DEFAULT_OFFICIAL_SOURCES, fetch_text


@dataclass
class WorkerContext:
    output_dir: Path
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    payloads: dict[str, dict[str, object]] = field(default_factory=dict)
    completed_operations: dict[str, dict[str, object]] = field(default_factory=dict)
    providers: dict[str, object] = field(default_factory=dict)
    request_as_of: str | None = None
    input_artifacts: dict[str, InputArtifactRef] = field(default_factory=dict)
    clock: Callable[[], datetime] = field(default_factory=lambda: lambda: datetime.now(ZoneInfo("Asia/Shanghai")))


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


def _price_input(operation: ExecutionOperation, context: WorkerContext
                 ) -> tuple[pd.DataFrame, dict[str, object], list[str]]:
    """Bind one explicit market input to the requested identity and closed-day scope.

    Inline data are arithmetic fixtures, not proof of a historical market vintage.
    An absent explicit dependency is never permission to fetch a replacement.
    """
    from tempfile import TemporaryDirectory

    from .market_worker import _bounded_frame, _symbol, _window, run_market_data_resilient

    params = operation.parameters
    symbol = _symbol(params)
    first, end, _ = _window(params, context)
    has_dep = "depends_on_operation_ids" in params
    has_inline = "inline_ohlcv" in params
    if has_dep and has_inline:
        raise ValueError("PRICE_INPUT_DEPENDENCY_INLINE_CONFLICT")
    if has_inline:
        inline = params["inline_ohlcv"]
        if not isinstance(inline, list) or not 0 < len(inline) <= 4000 or not all(
                isinstance(row, dict) for row in inline):
            raise ValueError("PRICE_INLINE_INPUT_INVALID")
        frame = _bounded_frame(pd.DataFrame(inline), first, end)
        return frame, {"kind": "INLINE_CALLER_DATA", "source_operation_id": None,
                       "input_bars_sha256": canonical_sha256(_jsonable_records(frame)),
                       "adjust": params.get("adjust"), "pit_safe": False,
                       "historical_vintage_verified": False}, []

    if has_dep:
        deps = params["depends_on_operation_ids"]
        if not isinstance(deps, list) or len(deps) != 1 or not isinstance(deps[0], str):
            raise ValueError("PRICE_EXACTLY_ONE_MARKET_DEPENDENCY_REQUIRED")
        dep = deps[0]
        provenance = context.completed_operations.get(dep)
        payload = context.payloads.get(dep)
        frame = context.frames.get(dep)
        if (not isinstance(provenance, dict) or provenance.get("kind") != "MARKET_DATA"
                or provenance.get("status") not in {"PASS", "WARN"}
                or not isinstance(payload, dict) or frame is None):
            raise ValueError("PRICE_MARKET_DEPENDENCY_NOT_USABLE")
        if (provenance.get("as_of") != params["as_of"] or payload.get("as_of") != params["as_of"]
                or payload.get("symbol") != symbol):
            raise ValueError("PRICE_MARKET_DEPENDENCY_IDENTITY_OR_CUTOFF_MISMATCH")
        start_source = date.fromisoformat(payload["start"])
        end_source = date.fromisoformat(payload["end"])
        if start_source > end_source or end_source > end:
            raise ValueError("PRICE_MARKET_DEPENDENCY_WINDOW_MISMATCH")
        if "history_days" in params and first > start_source:
            raise ValueError("PRICE_MARKET_DEPENDENCY_WINDOW_MISMATCH")
        source_adjust = payload.get("adjust")
        if source_adjust not in ("", "qfq", "hfq"):
            raise ValueError("PRICE_MARKET_DEPENDENCY_BASIS_UNKNOWN")
        if "adjust" in params and ("" if params["adjust"] == "none" else params["adjust"]) != source_adjust:
            raise ValueError("PRICE_MARKET_DEPENDENCY_BASIS_MISMATCH")
        frame = _bounded_frame(frame, start_source, end_source)
        # Verify the exact consumed OHLCV values against the sealed upstream
        # payload, rather than accepting an unrelated in-memory frame.
        records = payload.get("bars")
        if not isinstance(records, list) or len(records) != len(frame):
            raise ValueError("PRICE_MARKET_DEPENDENCY_RECORDS_MISMATCH")
        observed = _bounded_frame(pd.DataFrame(records), start_source, end_source)
        if _jsonable_records(frame) != records:
            raise ValueError("PRICE_MARKET_DEPENDENCY_RECORDS_MISMATCH")
        # Compute from the serialized upstream rows that are actually delivered,
        # not extra floating-point precision absent from the upstream artifact.
        return observed, {"kind": "MARKET_DATA_DEPENDENCY", "source_operation_id": dep,
                       "input_bars_sha256": canonical_sha256(records),
                       "adjust": source_adjust, "source_window_end": end_source.isoformat(),
                       "pit_safe": False, "historical_vintage_verified": False}, [
                           "PRICE_MARKET_HISTORICAL_VINTAGE_UNVERIFIED"]

    # Keep standalone price operations available, but use the same bounded
    # market adapter as MARKET_DATA. No old in-process implicit network calls.
    market_params = {k: params[k] for k in ("subject_ids", "as_of", "history_days",
                     "history_end_offset_days", "adjust", "price_tolerance") if k in params}
    with TemporaryDirectory(prefix="price-market-") as folder:
        temp = WorkerContext(output_dir=Path(folder), request_as_of=context.request_as_of,
                             clock=context.clock)
        source = ExecutionOperation(operation_id="implicit-market", kind="MARKET_DATA",
                                    parameters=market_params)
        result = run_market_data_resilient(source, temp)
        if result.status not in {"PASS", "WARN"}:
            raise ValueError("PRICE_IMPLICIT_MARKET_BLOCKED:" + ",".join(result.errors))
        frame = temp.frames["implicit-market"]
        payload = temp.payloads["implicit-market"]
        records = payload["bars"]
        if _jsonable_records(frame) != records:
            raise ValueError("PRICE_IMPLICIT_MARKET_RECORDS_MISMATCH")
        observed = _bounded_frame(pd.DataFrame(records), date.fromisoformat(payload["start"]),
                                  date.fromisoformat(payload["end"]))
        return observed, {"kind": "BOUNDED_IMPLICIT_MARKET", "source_operation_id": None,
                              "input_bars_sha256": canonical_sha256(records),
                              "adjust": payload["adjust"], "source_window_end": payload["end"],
                              "market_observation": payload,
                              "pit_safe": False, "historical_vintage_verified": False}, [
                                  "IMPLICIT_MARKET_FETCH_BOUNDED", *result.warnings]


def _price_input_block(operation: ExecutionOperation, exc: Exception) -> OperationResult:
    code = str(exc)
    if not code.startswith(("PRICE_", "MARKET_", "EVENT_")):
        code = "PRICE_INPUT_INVALID:" + type(exc).__name__
    return OperationResult(operation_id=operation.operation_id, status="BLOCK",
                           exit_code=2, errors=[code])


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
    low_52 = float(last_252.min()) if len(last_252) == 252 else None
    high_52 = float(last_252.max()) if len(last_252) == 252 else None
    position_52w = (float((close.iloc[-1] - low_52) / (high_52 - low_52))
                    if high_52 is not None and low_52 is not None and high_52 > low_52 else None)

    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    prior_close = close.shift(1)
    true_range = pd.concat(
        [(high - low).abs(), (high - prior_close).abs(), (low - prior_close).abs()],
        axis=1,
    ).max(axis=1)
    last_20_returns = returns.dropna().tail(20)
    downside = last_20_returns[last_20_returns < 0]
    volume_avg20 = float(volume.tail(20).mean()) if len(volume) >= 20 else None
    return {
        "close": float(close.iloc[-1]),
        "return_5d": horizon_return(5),
        "return_20d": horizon_return(20),
        "return_60d": horizon_return(60),
        "return_120d": horizon_return(120),
        "return_250d": horizon_return(250),
        "moving_average": {f"ma{window}": ma(window) for window in (5, 10, 20, 60, 120, 250)},
        "realized_vol_20d": (
            float(last_20_returns.std(ddof=1) * math.sqrt(252)) if len(last_20_returns) == 20 else None
        ),
        "downside_vol_20d": (
            float(downside.std(ddof=1) * math.sqrt(252)) if len(last_20_returns) == 20 and len(downside) >= 2 else None
        ),
        "atr14": float(true_range.tail(14).mean()) if len(frame) >= 15 else None,
        "max_drawdown": float(drawdowns.min()),
        "drawdown_now": float(drawdowns.iloc[-1]),
        "position_52w": position_52w,
        "distance_to_52w_high": float(close.iloc[-1] / high_52 - 1.0) if high_52 is not None else None,
        "volume_ratio_20d": float(volume.iloc[-1] / volume_avg20) if volume_avg20 else None,
        "rows": len(frame),
        "first_date": str(frame["date"].iloc[0].date()),
        "last_date": str(frame["date"].iloc[-1].date()),
    }


def run_price_analytics(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    try:
        frame, source, warnings = _price_input(operation, context)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, ProviderError) as exc:
        return _price_input_block(operation, exc)
    context.frames[operation.operation_id] = frame
    metrics = _price_metrics(frame)
    payload = {
        "symbol": _subject(operation.parameters),
        "as_of": operation.parameters["as_of"],
        "metrics": metrics,
        "metric_basis": {"lookbacks": "OBSERVED_ROWS_NOT_VERIFIED_TRADING_SESSIONS",
                         "annualization_assumption": 252,
                         "downside_vol_20d": "SAMPLE_SD_OF_NEGATIVE_RETURNS_WITHIN_LAST_20_RETURNS",
                         "position_52w": "252_OBSERVED_CLOSES_REQUIRED",
                         "atr14": "SIMPLE_MEAN_OF_14_TRUE_RANGES_WITH_PRIOR_CLOSE",
                         "volume_ratio_20d": "LATEST_OVER_MEAN_OF_LAST_20_ROWS_INCLUDING_LATEST"},
        "price_input": source,
        "pit_safe": False,
        "historical_vintage_verified": False,
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
    try:
        frame, source, warnings = _price_input(operation, context)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, ProviderError) as exc:
        return _price_input_block(operation, exc)
    context.frames[operation.operation_id] = frame
    png_path = context.output_dir / f"{operation.operation_id}.png"
    json_path = context.output_dir / f"{operation.operation_id}.json"
    renderer = "mplfinance"
    try:
        import mplfinance as mpf

        plot = frame[["date", "open", "high", "low", "close", "volume"]].copy()
        plot = plot.set_index("date")
        plot.columns = ["Open", "High", "Low", "Close", "Volume"]
        mav = tuple(window for window in (20, 60, 120) if min(len(plot), 260) >= window)
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
        "as_of": operation.parameters["as_of"],
        "renderer": renderer,
        "price_input": source,
        "pit_safe": False,
        "historical_vintage_verified": False,
        "first_rendered_date": frame["date"].tail(260).iloc[0].date().isoformat(),
        "last_rendered_date": frame["date"].iloc[-1].date().isoformat(),
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


def _valuation_date(value: object) -> date:
    """Accept only an unambiguous day from the provider's daily valuation table."""
    if pd.isna(value):
        raise ValueError("missing valuation date")
    if isinstance(value, datetime):
        if value.tzinfo is not None or any((value.hour, value.minute, value.second, value.microsecond)):
            raise ValueError("valuation date is not a plain day")
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError("unsupported valuation date type")
    parsed = date.fromisoformat(value)
    if value != parsed.isoformat():
        raise ValueError("valuation date must be YYYY-MM-DD")
    return parsed


def run_valuation_history(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    """Return a date-bounded provider observation, never attest historical vintage."""
    def blocked(reason: str) -> OperationResult:
        return OperationResult(operation_id=operation.operation_id, status="BLOCK",
                               exit_code=2, errors=[reason])

    subjects = operation.parameters.get("subject_ids")
    if (not isinstance(subjects, list) or len(subjects) != 1
            or not isinstance(subjects[0], str)
            or len(subjects[0]) != 6 or not subjects[0].isascii() or not subjects[0].isdigit()):
        return blocked("VALUATION_REQUIRES_ONE_EXACT_SIX_DIGIT_SYMBOL")
    symbol = subjects[0]
    try:
        cutoff = _valuation_date(operation.parameters.get("as_of"))
    except (ValueError, TypeError):
        return blocked("VALUATION_REQUIRES_EXACT_CALENDAR_DATE")
    if cutoff > datetime.now(ZoneInfo("Asia/Shanghai")).date():
        return blocked("VALUATION_FUTURE_CUTOFF")
    provider = AKShareResearchProvider()
    frame = provider.get_valuation_history(symbol)
    observed_at = datetime.now(UTC)
    if frame.empty or not frame.columns.is_unique:
        return blocked("VALUATION_EMPTY_OR_AMBIGUOUS_SCHEMA")
    columns = [name for name in ("数据日期", "date") if name in frame.columns]
    if len(columns) != 1:
        return blocked("VALUATION_DATE_COLUMN_MISSING_OR_AMBIGUOUS")
    date_column = columns[0]
    try:
        dates = [_valuation_date(value) for value in frame[date_column]]
    except (ValueError, TypeError, OverflowError):
        return blocked("VALUATION_INVALID_PROVIDER_DATE")
    # A duplicate day can represent conflicting revisions. Do not guess which
    # retained record is the version available at the requested cutoff.
    eligible = [(day, index) for index, day in enumerate(dates) if day <= cutoff]
    if not eligible:
        return blocked("VALUATION_NO_ROWS_AT_OR_BEFORE_CUTOFF")
    if len({day for day, _ in eligible}) != len(eligible):
        return blocked("VALUATION_DUPLICATE_ELIGIBLE_DATES")
    eligible.sort()
    bounded = frame.iloc[[index for _, index in eligible]].copy()
    bounded[date_column] = [day.isoformat() for day, _ in eligible]
    warnings = ["VALUATION_HISTORICAL_AVAILABILITY_UNVERIFIED",
                "VALUATION_SINGLE_PROVIDER_NOT_INDEPENDENTLY_CROSSCHECKED"]
    if len(eligible) < len(frame):
        warnings.append("VALUATION_ROWS_AFTER_CUTOFF_EXCLUDED")
    payload = {
        "symbol": symbol,
        "as_of": cutoff.isoformat(),
        "observed_at": observed_at.isoformat(),
        "provider": "AKShare.stock_value_em (Eastmoney)",
        "date_column": date_column,
        "latest_data_date": eligible[-1][0].isoformat(),
        "records": _jsonable_records(bounded),
        "rows": len(bounded),
        "excluded_after_cutoff": len(frame) - len(bounded),
        "pit_safe": False,
        "historical_vintage_verified": False,
        "decision_authority": False,
        "warnings": warnings,
    }
    context.payloads[operation.operation_id] = payload
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    return OperationResult(
        operation_id=operation.operation_id,
        status="WARN",
        exit_code=0,
        artifacts=[_artifact(path, media_type="application/json")],
        metrics={"rows": len(bounded), "excluded_after_cutoff": len(frame) - len(bounded)},
        warnings=warnings,
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
