"""Public A-share universe acquisition with explicit freshness and source evidence."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .contracts import ArtifactRef, ExecutionOperation, OperationResult, canonical_sha256
from .workers import WorkerContext

_SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_MIN_UNIVERSE_SIZE = 1000
SCHEMA_VERSION = "1.0"
_SINA_MAX_ATTEMPTS = 3
_SINA_TIMEOUT_SECONDS = 10
_SINA_PAGE_SIZE = 80
_SINA_MAX_PAGES = 2000
_SINA_RAW_COLUMNS = (
    "symbol",
    "code",
    "name",
    "trade",
    "pricechange",
    "changepercent",
    "buy",
    "sell",
    "settlement",
    "open",
    "high",
    "low",
    "volume",
    "amount",
    "ticktime",
    "per",
    "pb",
    "mktcap",
    "nmc",
    "turnoverratio",
)


@dataclass(frozen=True)
class _SinaPagePlan:
    expected_total_rows: int
    page_count: int

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "code": ("代码", "证券代码", "code", "symbol"),
    "name": ("名称", "证券简称", "name", "security_name"),
    "latest_price": ("最新价", "最新价格", "trade", "latest_price", "price"),
    "pct_change": ("涨跌幅", "changepercent", "pct_change", "change_percent", "change_pct"),
    "volume": ("成交量", "volume"),
    "amount": ("成交额", "amount", "turnover_amount"),
    "amplitude": ("振幅", "amplitude"),
    "turnover_rate": ("换手率", "turnoverratio", "turnover_rate"),
    "pe_dynamic": ("市盈率-动态", "市盈率", "per", "pe_dynamic"),
    "pb": ("市净率", "pb"),
    "total_market_cap": ("总市值", "mktcap", "total_market_cap"),
    "float_market_cap": ("流通市值", "nmc", "float_market_cap"),
    "change_60d": ("60日涨跌幅", "change_60d"),
    "ytd_change": ("年初至今涨跌幅", "ytd_change"),
    "quote_trade_date": ("行情日期", "交易日期", "quote_trade_date", "trade_date"),
}

_MAINLAND_A_SHARE_PREFIXES = {
    "000",
    "001",
    "002",
    "003",
    "004",
    "300",
    "301",
    "302",
    "303",
    "600",
    "601",
    "603",
    "605",
    "688",
    "689",
    "920",
}
_REQUIRED_FIELDS = ("code", "name", "latest_price", "pct_change", "volume", "amount")
_OPTIONAL_NUMERIC_FIELDS = (
    "amplitude",
    "turnover_rate",
    "pe_dynamic",
    "pb",
    "total_market_cap",
    "float_market_cap",
    "change_60d",
    "ytd_change",
)
_NUMERIC_FIELDS = set(_REQUIRED_FIELDS[2:]) | set(_OPTIONAL_NUMERIC_FIELDS)


def _artifact(path: Path) -> ArtifactRef:
    return ArtifactRef(
        path=path.name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        media_type="application/json",
        size_bytes=path.stat().st_size,
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _column(frame: pd.DataFrame, field: str) -> pd.Series | None:
    for name in _FIELD_ALIASES[field]:
        if name in frame.columns:
            return frame[name]
    return None


def _code(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().lower()
    if text[:2] in {"sh", "sz", "bj"}:
        text = text[2:]
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if not text.isdigit():
        return None
    text = text.zfill(6)
    if len(text) != 6 or text.startswith(("200", "399", "900")):
        return None
    if text[:3] not in _MAINLAND_A_SHARE_PREFIXES and text[0] not in {"4", "8"}:
        return None
    return text


def _name(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text if text and text.casefold() != "nan" else None


def _number(value: object) -> float | None:
    converted = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(converted):
        return None
    number = float(converted)
    return number if math.isfinite(number) else None


def _quote_date(frame: pd.DataFrame) -> str | None:
    series = _column(frame, "quote_trade_date")
    if series is None:
        return None
    parsed = pd.to_datetime(series, errors="coerce").dropna().dt.date.unique()
    if len(parsed) != 1:
        return None
    return parsed[0].isoformat()


def _normalize_snapshot(
    frame: object,
    *,
    volume_multiplier: int,
) -> tuple[pd.DataFrame, dict[str, int], str | None]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("empty snapshot")
    columns = {field: _column(frame, field) for field in _FIELD_ALIASES}
    if any(columns[field] is None for field in _REQUIRED_FIELDS):
        missing = [field for field in _REQUIRED_FIELDS if columns[field] is None]
        raise ValueError("missing required fields: " + ",".join(missing))

    records: list[dict[str, object]] = []
    invalid = 0
    for index in range(len(frame)):
        record: dict[str, object] = {
            "asset": _code(columns["code"].iloc[index]),
            "name": _name(columns["name"].iloc[index]),
        }
        if record["asset"] is None or record["name"] is None:
            invalid += 1
            continue
        record["code"] = record["asset"]
        valid = True
        for field in _NUMERIC_FIELDS:
            series = columns.get(field)
            if series is None:
                continue
            value = _number(series.iloc[index])
            if field in _REQUIRED_FIELDS and value is None:
                valid = False
                break
            if value is not None:
                if field == "volume":
                    value *= volume_multiplier
                record[field] = value
        if not valid:
            invalid += 1
            continue
        records.append(record)

    records.sort(key=lambda item: str(item["code"]))
    before_dedupe = len(records)
    deduped = pd.DataFrame(records).drop_duplicates("code", keep="first") if records else pd.DataFrame()
    duplicate_count = before_dedupe - len(deduped)
    if not deduped.empty:
        ordered = [
            field
            for field in ("asset", "code", "name", *_REQUIRED_FIELDS[2:], *_OPTIONAL_NUMERIC_FIELDS)
            if field in deduped
        ]
        deduped = deduped[ordered].reset_index(drop=True)
    stats = {
        "raw_row_count": len(frame),
        "invalid_row_count": invalid,
        "duplicate_row_count": duplicate_count,
    }
    return deduped, stats, _quote_date(frame)


def _listing_crosscheck(frame: pd.DataFrame, listings: object) -> dict[str, object]:
    if not isinstance(listings, pd.DataFrame) or listings.empty:
        raise ValueError("empty listing reference")
    code_series = _column(listings, "code")
    if code_series is None:
        raise ValueError("listing code field missing")
    listing_codes = {code for code in (_code(value) for value in code_series) if code is not None}
    universe_codes = set(frame["code"]) if not frame.empty else set()
    if not listing_codes:
        raise ValueError("listing reference has no valid codes")
    overlap = universe_codes & listing_codes
    name_mismatch_count = 0
    name_mismatch_sample: list[str] = []
    name_series = _column(listings, "name")
    if name_series is not None:
        listing_names: dict[str, str] = {}
        for index, value in enumerate(code_series):
            code = _code(value)
            name = _name(name_series.iloc[index])
            if code is not None and name is not None:
                listing_names.setdefault(code, name)
        for record in frame.to_dict(orient="records"):
            code = str(record["code"])
            expected_name = _name(record.get("name"))
            if code in listing_names and expected_name != listing_names[code]:
                name_mismatch_count += 1
                if len(name_mismatch_sample) < 5:
                    name_mismatch_sample.append(code)
    else:
        name_mismatch_count = -1
    crosscheck_status = (
        "MATCH"
        if overlap == universe_codes and name_mismatch_count == 0
        else "WARN"
    )
    return {
        "status": crosscheck_status,
        "overlap_rows": len(overlap),
        "universe_rows": len(universe_codes),
        "listing_row_count": len(listings),
        "missing_in_listing": len(universe_codes - listing_codes),
        "name_mismatch_count": name_mismatch_count,
        "name_mismatch_sample": name_mismatch_sample,
    }


def _now(context: WorkerContext) -> tuple[date, str]:
    value = context.clock()
    if isinstance(value, date) and not isinstance(value, datetime):
        local = datetime.combine(value, datetime.min.time(), tzinfo=_SHANGHAI)
    elif value.tzinfo is None:
        local = value.replace(tzinfo=_SHANGHAI)
    else:
        local = value.astimezone(_SHANGHAI)
    return local.date(), local.astimezone(UTC).isoformat()


def _provider(context: WorkerContext) -> Any:
    injected = context.providers.get("akshare")
    if injected is not None:
        return injected
    # Official endpoint contract: https://akshare.akfamily.xyz/data/stock/stock.html
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError("akshare is not installed") from exc
    return ak


def _decode_sina_page(text: str, decode: Callable[[str], object]) -> pd.DataFrame:
    decoded = decode(text)
    if not isinstance(decoded, list) or not decoded:
        raise ValueError("Sina page is not a non-empty list")
    frame = pd.DataFrame(decoded)
    if frame.empty:
        raise ValueError("Sina page is empty")
    if all(isinstance(column, int) for column in frame.columns):
        if frame.shape[1] != len(_SINA_RAW_COLUMNS):
            raise ValueError("Sina page has unexpected column count")
        frame.columns = list(_SINA_RAW_COLUMNS)
    return frame


def _sina_request_with_retry(
    get: Callable[..., Any],
    *,
    url: str,
    params: dict[str, str] | None,
    description: str,
    parse: Callable[[str], object],
) -> object:
    last_error: Exception | None = None
    for _attempt in range(1, _SINA_MAX_ATTEMPTS + 1):
        try:
            if params is None:
                response = get(url, timeout=_SINA_TIMEOUT_SECONDS)
            else:
                response = get(url, params=params, timeout=_SINA_TIMEOUT_SECONDS)
            response.raise_for_status()
            return parse(response.text)
        except Exception as exc:  # noqa: BLE001 - bounded provider boundary.
            last_error = exc
    raise RuntimeError(f"Sina {description} failed after {_SINA_MAX_ATTEMPTS} attempts") from last_error


def _sina_page_count(text: str) -> _SinaPagePlan:
    matches = re.findall(r"\d+", text)
    if not matches:
        raise ValueError("Sina page count is missing")
    total_rows = int(matches[0])
    if total_rows <= 0:
        raise ValueError("Sina page count is empty")
    page_count = (total_rows + _SINA_PAGE_SIZE - 1) // _SINA_PAGE_SIZE
    if page_count > _SINA_MAX_PAGES:
        raise ValueError("Sina page count exceeds bounded limit")
    return _SinaPagePlan(expected_total_rows=total_rows, page_count=page_count)


def _sina_adapter(module: object | None = None) -> dict[str, object]:
    """Validate and isolate all AKShare internal Sina-module access."""
    if module is None:
        try:
            import akshare
            import akshare.stock.stock_zh_a_sina as module
        except ImportError as exc:
            raise RuntimeError("AKShare Sina adapter contract unavailable") from exc
        package_version = getattr(akshare, "__version__", "UNKNOWN")
    else:
        package_version = getattr(module, "__version__", "UNKNOWN")
    required = (
        "requests",
        "demjson",
        "zh_sina_a_stock_count_url",
        "zh_sina_a_stock_url",
        "zh_sina_a_stock_payload",
    )
    missing = [name for name in required if not hasattr(module, name)]
    requests_module = getattr(module, "requests", None)
    demjson_module = getattr(module, "demjson", None)
    if missing or not callable(getattr(requests_module, "get", None)) or not callable(
        getattr(demjson_module, "decode", None)
    ) or not isinstance(getattr(module, "zh_sina_a_stock_payload", None), dict):
        raise RuntimeError("AKShare Sina adapter contract unavailable")
    return {
        "get": requests_module.get,
        "decode": demjson_module.decode,
        "count_url": module.zh_sina_a_stock_count_url,
        "data_url": module.zh_sina_a_stock_url,
        "payload": dict(module.zh_sina_a_stock_payload),
        "adapter_contract": "akshare.stock.stock_zh_a_sina",
        "adapter_version": str(package_version),
    }


def _fetch_sina_pages(
    *,
    get: Callable[..., Any] | None = None,
    decode: Callable[[str], object] | None = None,
    count_url: str | None = None,
    data_url: str | None = None,
    payload: dict[str, str] | None = None,
    adapter: dict[str, object] | None = None,
) -> pd.DataFrame:
    """Fetch every Sina page with bounded retries and no silent partial result."""
    if get is None or decode is None or count_url is None or data_url is None or payload is None:
        adapter = adapter or _sina_adapter()
        get = get or adapter["get"]
        decode = decode or adapter["decode"]
        count_url = count_url or adapter["count_url"]
        data_url = data_url or adapter["data_url"]
        payload = payload or adapter["payload"]

    page_plan = _sina_request_with_retry(
        get,
        url=count_url,
        params=None,
        description="page count",
        parse=_sina_page_count,
    )
    if not isinstance(page_plan, _SinaPagePlan):
        raise RuntimeError("Sina page count parser returned an invalid value")

    pages: list[pd.DataFrame] = []
    seen_codes: set[str] = set()
    for page in range(1, page_plan.page_count + 1):
        page_payload = dict(payload)
        page_payload["page"] = str(page)
        page_frame = _sina_request_with_retry(
            get,
            url=data_url,
            params=page_payload,
            description=f"page {page}",
            parse=lambda text, decoder=decode: _decode_sina_page(text, decoder),
        )
        if not isinstance(page_frame, pd.DataFrame) or page_frame.empty:
            raise RuntimeError(f"Sina page {page} parser returned no rows")
        expected_rows = (
            _SINA_PAGE_SIZE
            if page < page_plan.page_count
            else page_plan.expected_total_rows - _SINA_PAGE_SIZE * (page_plan.page_count - 1)
        )
        if len(page_frame) != expected_rows:
            raise RuntimeError(f"Sina page {page} expected {expected_rows} rows, got {len(page_frame)}")
        code_series = _column(page_frame, "code")
        if code_series is not None:
            for raw_code in code_series:
                code = _code(raw_code)
                if code is not None and code in seen_codes:
                    raise RuntimeError(f"Sina duplicate A-share code: {code}")
                if code is not None:
                    seen_codes.add(code)
        pages.append(page_frame)
    frame = pd.concat(pages, ignore_index=True)
    if len(frame) != page_plan.expected_total_rows:
        raise RuntimeError(
            f"Sina expected {page_plan.expected_total_rows} rows, got {len(frame)}"
        )
    return frame


def _fetch_sina_snapshot(context: WorkerContext, provider: Any) -> object:
    injected = context.providers.get("akshare_sina_paged")
    if injected is not None:
        if not callable(injected):
            raise TypeError("akshare_sina_paged must be callable")
        return injected(), {
            "adapter_contract": "injected.sina_paged",
            "adapter_version": "TEST_OR_INJECTED",
        }
    paged = getattr(provider, "stock_zh_a_spot_pages", None)
    if callable(paged):
        return paged(), {
            "adapter_contract": "provider.stock_zh_a_spot_pages",
            "adapter_version": "TEST_OR_INJECTED",
        }
    adapter = _sina_adapter()
    return _fetch_sina_pages(adapter=adapter), {
        "adapter_contract": adapter["adapter_contract"],
        "adapter_version": adapter["adapter_version"],
    }


def run_market_universe(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    parameters = operation.parameters
    raw_market = parameters.get("market")
    market = "CN_A" if raw_market is None or not str(raw_market).strip() else str(raw_market).strip().upper()
    raw_asset_type = parameters.get("asset_type")
    asset_type = "STOCK" if raw_asset_type is None or not str(raw_asset_type).strip() else str(raw_asset_type).strip().upper()
    if market != "CN_A" or asset_type != "STOCK":
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=["MARKET_UNIVERSE_SCOPE_UNSUPPORTED"],
            metrics={"market": market, "asset_type": asset_type},
        )
    raw_as_of = parameters.get("as_of")
    try:
        operation_as_of = date.fromisoformat(str(raw_as_of)[:10])
    except (TypeError, ValueError):
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=["MARKET_UNIVERSE_AS_OF_REQUIRED"],
        )

    try:
        request_as_of = date.fromisoformat(str(context.request_as_of)[:10])
    except (TypeError, ValueError):
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=["MARKET_UNIVERSE_REQUEST_AS_OF_REQUIRED"],
        )
    if operation_as_of != request_as_of:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=["MARKET_UNIVERSE_AS_OF_MISMATCH"],
            metrics={
                "operation_as_of": operation_as_of.isoformat(),
                "request_as_of": request_as_of.isoformat(),
            },
        )
    as_of = request_as_of
    today, retrieved_at = _now(context)
    if as_of != today:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=["MARKET_UNIVERSE_HISTORICAL_SNAPSHOT_UNSUPPORTED"],
            metrics={"as_of": as_of.isoformat(), "today_asia_shanghai": today.isoformat()},
        )

    try:
        minimum = int(parameters.get("min_universe_size") or DEFAULT_MIN_UNIVERSE_SIZE)
    except (TypeError, ValueError):
        minimum = DEFAULT_MIN_UNIVERSE_SIZE
    minimum = max(1, min(minimum, 100_000))
    try:
        provider = _provider(context)
    except Exception as exc:  # noqa: BLE001 - dependency availability is structured evidence.
        payload = {
            "source": "public_market_data",
            "provider": "akshare",
            "market": market,
            "asset_type": asset_type,
            "public_data_only": True,
            "primary_provider": None,
            "as_of": as_of.isoformat(),
            "retrieved_at": retrieved_at,
            "quote_trade_date": None,
            "quote_trade_date_status": "UNKNOWN",
            "schema_version": SCHEMA_VERSION,
            "schema_fingerprint": canonical_sha256([]),
            "row_count": 0,
            "raw_row_count": 0,
            "invalid_row_count": 0,
            "duplicate_row_count": 0,
            "min_universe_size": minimum,
            "listing_crosscheck": {"status": "NOT_RUN", "overlap_rows": 0},
            "provider_history": [{"provider": "akshare", "status": "BLOCK", "error_type": type(exc).__name__}],
            "fallback_history": [],
            "quality_flags": ["MARKET_UNIVERSE_PROVIDER_UNAVAILABLE", "MARKET_UNIVERSE_QUOTE_DATE_UNVERIFIED"],
            "warnings": ["MARKET_UNIVERSE_QUOTE_DATE_UNVERIFIED"],
            "records": [],
            "decision_authority": False,
        }
        context.payloads[operation.operation_id] = payload
        path = context.output_dir / f"{operation.operation_id}.json"
        _write_json(path, payload)
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            artifacts=[_artifact(path)],
            metrics={"row_count": 0, "min_universe_size": minimum},
            warnings=payload["warnings"],
            errors=["MARKET_UNIVERSE_PROVIDER_UNAVAILABLE"],
        )
    provider_history: list[dict[str, object]] = []
    frame = pd.DataFrame()
    stats = {"raw_row_count": 0, "invalid_row_count": 0, "duplicate_row_count": 0}
    quote_trade_date: str | None = None
    primary_provider: str | None = None
    fallback_used = False
    adapter_provenance: dict[str, object] = {}

    for endpoint in ("stock_zh_a_spot_em", "stock_zh_a_spot"):
        if endpoint == "stock_zh_a_spot" and not fallback_used:
            break
        if endpoint == "stock_zh_a_spot_em" and primary_provider is not None:
            break
        try:
            if endpoint == "stock_zh_a_spot_em":
                raw = getattr(provider, endpoint)()
            else:
                raw, adapter_provenance = _fetch_sina_snapshot(context, provider)
            volume_multiplier = 100 if endpoint.endswith("spot_em") else 1
            frame, stats, quote_trade_date = _normalize_snapshot(
                raw,
                volume_multiplier=volume_multiplier,
            )
            primary_provider = "akshare_em" if endpoint.endswith("spot_em") else "akshare_sina"
            history_entry: dict[str, object] = {
                "provider": "akshare",
                "endpoint": endpoint,
                "status": "PASS",
                "rows": len(frame),
            }
            if endpoint == "stock_zh_a_spot":
                history_entry.update(adapter_provenance)
            provider_history.append(history_entry)
        except Exception as exc:  # noqa: BLE001 - provider boundary becomes evidence.
            provider_history.append(
                {
                    "provider": "akshare",
                    "endpoint": endpoint,
                    "status": "BLOCK",
                    "error_type": type(exc).__name__,
                }
            )
            if endpoint.endswith("spot_em"):
                fallback_used = True

    warnings: list[str] = []
    errors: list[str] = []
    if primary_provider is None:
        errors.append("MARKET_UNIVERSE_NO_SNAPSHOT")
    elif fallback_used:
        warnings.append("MARKET_UNIVERSE_PRIMARY_FAILED_SINA_FALLBACK")

    listing_crosscheck: dict[str, object]
    if primary_provider is None:
        listing_crosscheck = {"status": "NOT_RUN", "overlap_rows": 0}
    else:
        try:
            listing_crosscheck = _listing_crosscheck(frame, provider.stock_info_a_code_name())
            if listing_crosscheck["status"] != "MATCH":
                warnings.append("MARKET_UNIVERSE_LISTING_CROSSCHECK_WARN")
            if listing_crosscheck.get("name_mismatch_count", 0) > 0:
                warnings.append("MARKET_UNIVERSE_LISTING_NAME_MISMATCH")
        except Exception as exc:  # noqa: BLE001 - listing is quality evidence, not a hard firewall.
            listing_crosscheck = {"status": "UNAVAILABLE", "overlap_rows": 0, "error_type": type(exc).__name__}
            warnings.append("MARKET_UNIVERSE_LISTING_CROSSCHECK_UNAVAILABLE")

    quality_flags: list[str] = []
    if quote_trade_date is None:
        quality_flags.append("MARKET_UNIVERSE_QUOTE_DATE_UNVERIFIED")
        warnings.append("MARKET_UNIVERSE_QUOTE_DATE_UNVERIFIED")
    elif quote_trade_date != as_of.isoformat():
        quality_flags.append("MARKET_UNIVERSE_QUOTE_DATE_MISMATCH")
        warnings.append("MARKET_UNIVERSE_QUOTE_DATE_MISMATCH")
    if stats["invalid_row_count"] or stats["duplicate_row_count"]:
        quality_flags.append("MARKET_UNIVERSE_ROWS_FILTERED")
        warnings.append("MARKET_UNIVERSE_ROWS_FILTERED")

    quote_trade_date_status = "UNKNOWN"
    if quote_trade_date is not None:
        quote_trade_date_status = (
            "VERIFIED" if quote_trade_date == as_of.isoformat() else "MISMATCH"
        )

    row_count = len(frame)
    if primary_provider is not None and row_count < minimum:
        errors.append(f"MARKET_UNIVERSE_BELOW_MINIMUM:{row_count}<{minimum}")

    status = "BLOCK" if errors else ("WARN" if warnings else "PASS")
    payload = {
        "source": "public_market_data",
        "provider": "akshare",
        "market": market,
        "asset_type": asset_type,
        "public_data_only": True,
        "primary_provider": primary_provider,
        "as_of": as_of.isoformat(),
        "retrieved_at": retrieved_at,
        "quote_trade_date": quote_trade_date,
        "quote_trade_date_status": quote_trade_date_status,
        "volume_unit": "shares",
        "volume_transform": {
            "primary_em_source_unit": "hands",
            "primary_em_multiplier": 100,
            "sina_source_unit": "shares",
        },
        "schema_version": SCHEMA_VERSION,
        "schema_fingerprint": canonical_sha256(list(frame.columns)),
        "row_count": row_count,
        **stats,
        "min_universe_size": minimum,
        "listing_crosscheck": listing_crosscheck,
        "provider_history": provider_history,
        "fallback_history": provider_history if fallback_used else [],
        "quality_flags": quality_flags,
        "warnings": warnings,
        "records": json.loads(frame.to_json(orient="records", force_ascii=False)) if not frame.empty else [],
        "decision_authority": False,
    }
    context.frames[operation.operation_id] = frame
    context.payloads[operation.operation_id] = payload
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    metrics = {
        "row_count": row_count,
        "raw_row_count": stats["raw_row_count"],
        "invalid_row_count": stats["invalid_row_count"],
        "duplicate_row_count": stats["duplicate_row_count"],
        "min_universe_size": minimum,
        "listing_overlap_rows": listing_crosscheck.get("overlap_rows", 0),
        "primary_provider": primary_provider,
        "provider_attempt_count": len(provider_history),
        "fallback_used": fallback_used,
    }
    return OperationResult(
        operation_id=operation.operation_id,
        status=status,
        exit_code=2 if status == "BLOCK" else 0,
        artifacts=[_artifact(path)],
        metrics=metrics,
        warnings=warnings,
        errors=errors,
    )
