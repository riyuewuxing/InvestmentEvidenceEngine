"""Public price-only retrospective control, not PIT replay or trading advice.

Fixed generic momentum experiment. No model selection, tuning, probability,
account, execution authority, or historical availability assertion.
"""
from __future__ import annotations

import base64
import hashlib
import sys
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from .bounded_worker import run_json_worker, write_worker_result
from .historical_capture import PublicSecurity
from .market_calendar import scheduled_days
from .market_worker import _bounded_frame, _crosscheck
from .momentum_profile import momentum_metrics, momentum_profile
from .snapshot_integrity import strict_json_loads

MAX_RAW_BYTES = 2 * 1024 * 1024


def parse_tencent_raw(raw: bytes, symbol: str, first: date, last: date) -> tuple[pd.DataFrame, int]:
    """Parse an explicit unadjusted day block, never qfq or a quote snapshot."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_RAW_BYTES:
        raise ValueError("TENCENT_BODY_INVALID")
    prefix = PublicSecurity(symbol=symbol, asset_type="STOCK").prefixed
    body = strict_json_loads(raw)
    if not isinstance(body, dict) or type(body.get("code")) is not int or body["code"] != 0:
        raise ValueError("TENCENT_RESPONSE_REJECTED")
    block = body.get("data")
    if not isinstance(block, dict) or prefix not in block or not isinstance(block[prefix], dict):
        raise ValueError("TENCENT_SYMBOL_BLOCK_MISSING")
    rows = block[prefix].get("day")
    if not isinstance(rows, list) or not 0 < len(rows) <= 756:
        raise ValueError("TENCENT_RAW_DAY_BLOCK_INVALID")
    records = []
    seen = set()
    excluded = 0
    for row in rows:
        if not isinstance(row, list) or len(row) < 6 or not isinstance(row[0], str):
            raise ValueError("TENCENT_ROW_INVALID")
        day = date.fromisoformat(row[0])
        if day.isoformat() != row[0] or day in seen:
            raise ValueError("TENCENT_DATE_INVALID_OR_DUPLICATE")
        seen.add(day)
        if not first <= day <= last:
            excluded += 1
            continue
        if any(type(value) not in {str, int, float} for value in row[1:6]):
            raise ValueError("TENCENT_PRICE_TYPE_INVALID")
        # Tencent raw daily order: date, open, close, high, low, volume.
        opening, close, high, low, volume = map(float, row[1:6])
        records.append({"date": day.isoformat(), "open": opening, "high": high,
                        "low": low, "close": close, "volume": volume})
    if not records:
        raise ValueError("TENCENT_NO_IN_SCOPE_BARS")
    return _bounded_frame(pd.DataFrame(records), first, last), excluded


def _child(symbol: str, first: date, last: date, out: Path) -> None:
    prefix = PublicSecurity(symbol=symbol, asset_type="STOCK").prefixed
    param = f"{prefix},day,{first.isoformat()},{last.isoformat()},756,"
    url = ("https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?"
           + urllib.parse.urlencode({"param": param}))
    started = datetime.now(UTC)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=12) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("TENCENT_HTTP_IDENTITY_INVALID")
        raw = response.read(MAX_RAW_BYTES + 1)
    if not 0 < len(raw) <= MAX_RAW_BYTES:
        raise ValueError("TENCENT_BODY_INVALID")
    write_worker_result(out, {"symbol": symbol, "first": first.isoformat(), "last": last.isoformat(),
                              "url": url, "started_at": started.isoformat(),
                              "retrieved_at": datetime.now(UTC).isoformat(),
                              "body_sha256": hashlib.sha256(raw).hexdigest(),
                              "body_base64": base64.b64encode(raw).decode("ascii")})


def acquire_tencent(symbol: str, first: date, last: date) -> tuple[pd.DataFrame | None, dict]:
    result = run_json_worker((sys.executable, "-m", "investment_evidence_engine.retrospective_control",
                              "--child", symbol, first.isoformat(), last.isoformat()),
                             timeout_seconds=25, max_bytes=3 * 1024 * 1024)
    info = {"provider": "tencent_direct", "status": "BLOCK",
            "worker_status": result.status, "elapsed_seconds": result.elapsed_seconds}
    if result.status != "OK" or result.payload is None:
        return None, info
    p = result.payload
    try:
        if (p["symbol"], p["first"], p["last"]) != (symbol, first.isoformat(), last.isoformat()):
            raise ValueError("TENCENT_CAPTURE_SCOPE_MISMATCH")
        start, end = datetime.fromisoformat(p["started_at"]), datetime.fromisoformat(p["retrieved_at"])
        if start.utcoffset() is None or end.utcoffset() is None or not start <= end <= datetime.now(UTC):
            raise ValueError("TENCENT_CAPTURE_TIME_INVALID")
        raw = base64.b64decode(p["body_base64"], validate=True)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != p["body_sha256"]:
            raise ValueError("TENCENT_BODY_DIGEST_MISMATCH")
        frame, excluded = parse_tencent_raw(raw, symbol, first, last)
    except (KeyError, ValueError, TypeError, RuntimeError) as exc:
        return None, info | {"worker_status": "PAYLOAD_INVALID", "error_type": type(exc).__name__}
    return frame, info | {"status": "OBSERVED", "url": p["url"],
                          "started_at": start.isoformat(), "retrieved_at": end.isoformat(),
                          "raw_body_sha256": digest, "raw_body_bytes": len(raw),
                          "raw_body_parent_rehash": "MATCH", "excluded_outside_window": excluded,
                          "rows": len(frame)}


def _metrics(gross: list[float], targets: list[int], bps: int) -> dict:
    return momentum_metrics(gross, targets, bps)


def retrospective_momentum(frame: pd.DataFrame, first: date, last: date) -> dict:
    """Prior-close signal, next-open interval, fixed split and friction stress.

    Only daily observed price intervals; no corporate distributions, fills,
    adjustment-vintage, or actual feasibility proof.
    """
    bars = _bounded_frame(frame, first, last)
    dates = tuple(bars["date"].dt.date)
    expected = tuple(row.day for row in scheduled_days(first, last) if row.is_trading_day)
    if dates != expected:
        raise ValueError("RETROSPECTIVE_SCHEDULE_COVERAGE_MISMATCH")
    if (bars["volume"] <= 0).any():
        raise ValueError("RETROSPECTIVE_ZERO_VOLUME_SESSION")
    return momentum_profile(dates, bars["close"].tolist(), bars["open"].tolist())


def same_window_comparison(left: pd.DataFrame, right: pd.DataFrame) -> dict:
    return _crosscheck(left, right, 0.001) | {"compared_fields": ["open", "high", "low", "close"],
                                               "volume_units_compared": False,
                                               "source_independence_verified": False}


if __name__ == "__main__":
    if len(sys.argv) != 6 or sys.argv[1] != "--child":
        raise SystemExit(2)
    _child(sys.argv[2], date.fromisoformat(sys.argv[3]), date.fromisoformat(sys.argv[4]), Path(sys.argv[5]))
