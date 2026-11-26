"""Bounded acquisition of public vendor-reported unadjusted daily closes.

No account, API credentials, forecasts, admission or raw vendor-body archive.
A result is an observed normalized table only. Third-party processes have
wall-clock limits, sanitized failure stages, and no retry loop.
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from .historical_reference import DailyClose, HistoricalCloseSeries, historical_pair_reference

SH = ZoneInfo("Asia/Shanghai")
PROVIDERS = ("eastmoney", "sina", "tencent")
MAX_CHILD_BYTES = 128 * 1024
CHILD_TIMEOUT = 25


class PublicSecurity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    symbol: str = Field(pattern=r"^[0-9]{6}$")
    asset_type: Literal["STOCK", "ETF"]

    @property
    def prefixed(self) -> str:
        if self.asset_type == "STOCK":
            if self.symbol.startswith(("60", "68")):
                return "sh" + self.symbol
            if self.symbol.startswith(("00", "30")):
                return "sz" + self.symbol
        elif self.asset_type == "ETF":
            if self.symbol.startswith(("51", "52", "56", "58")):
                return "sh" + self.symbol
            if self.symbol.startswith("159"):
                return "sz" + self.symbol
        raise ValueError("unsupported Shanghai/Shenzhen asset identity")


def validate_window(start: date, end: date, now: datetime) -> None:
    if type(start) is not date or type(end) is not date or now.utcoffset() is None:
        raise ValueError("explicit dates and timezone required")
    local = now.astimezone(SH)
    if not 20 <= (end - start).days <= 1100 or end > local.date():
        raise ValueError("invalid historical window")
    if end == local.date() and local.time() < time(15, 30):
        raise ValueError("current session not complete for observation")
    if end.weekday() >= 5:
        raise ValueError("terminal date cannot be a weekend")


def _from_rows(rows, subject: PublicSecurity, provider: str, start: date, end: date) -> HistoricalCloseSeries:
    if not isinstance(rows, list) or len(rows) > 756:
        raise ValueError("unexpected normalized row count")
    parsed = []
    for item in rows:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise ValueError("invalid normalized close row")
        day = date.fromisoformat(item[0])
        if not start <= day <= end or day.weekday() >= 5:
            raise ValueError("unexpected close date")
        if isinstance(item[1], bool):
            raise ValueError("boolean price")
        parsed.append(DailyClose(session=day, close=float(item[1])))
    parsed.sort(key=lambda item: item.session)
    series = HistoricalCloseSeries(subject_id=subject.symbol, currency="CNY",
        price_basis="RAW_CLOSE", source_label=provider, closes=tuple(parsed))
    if series.closes[-1].session != end:
        raise ValueError("terminal session missing")
    return series


def _provider_rows(source: str, subject: PublicSecurity, start: date, end: date):
    prefixed = subject.prefixed
    if source == "tencent":
        # Existing project adapter family; accept only an explicit raw "day"
        # block for the exact requested symbol, never qfqday or inferred quote.
        param = f"{prefixed},day,{start.isoformat()},{end.isoformat()},756,"
        url = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?" + urllib.parse.urlencode({"param": param})
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("provider body exceeds bound")
        payload = json.loads(raw)
        block = payload["data"][prefixed]
        if not isinstance(block, dict) or not isinstance(block.get("day"), list):
            raise ValueError("raw day block unavailable")
        return [[row[0], row[2]] for row in block["day"]]
    import akshare as ak
    import pandas as pd

    first, last = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    if source == "eastmoney":
        method = ak.stock_zh_a_hist if subject.asset_type == "STOCK" else ak.fund_etf_hist_em
        frame = method(symbol=subject.symbol, period="daily", start_date=first, end_date=last, adjust="")
        frame = frame.rename(columns={"日期": "date", "收盘": "close"})
    elif source == "sina" and subject.asset_type == "STOCK":
        frame = ak.stock_zh_a_daily(symbol=prefixed, start_date=first, end_date=last, adjust="")
    elif source == "sina":
        frame = ak.fund_etf_hist_sina(symbol=prefixed)
    else:
        raise ValueError("unknown provider")
    if frame is None or frame.empty or not {"date", "close"}.issubset(frame.columns):
        raise ValueError("empty or changed provider schema")
    sessions = pd.to_datetime(frame["date"], errors="raise").dt.date
    # All-history Sina ETF adapter explicitly clips to the requested window.
    # Other adapters are likewise bounded; never include a later session.
    return [[str(day), float(close)] for day, close in zip(sessions, frame["close"]) if start <= day <= end]


def _child(source: str, symbol: str, kind: str, first: str, last: str) -> None:
    stage = "REQUEST_VALIDATION"
    try:
        subject = PublicSecurity(symbol=symbol, asset_type=kind)
        start, end = date.fromisoformat(first), date.fromisoformat(last)
        validate_window(start, end, datetime.now(SH))
        stage = "PROVIDER_FETCH"
        # Keep provider text/errors out of the machine receipt.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rows = _provider_rows(source, subject, start, end)
        stage = "NORMALIZED_VALIDATION"
        series = _from_rows(rows, subject, source, start, end)
        print(json.dumps({"status": "OBSERVED", "series": series.model_dump(mode="json")}, allow_nan=False))
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "stage": stage, "error_type": type(exc).__name__}))


def acquire_series(source: str, subject: PublicSecurity, start: date, end: date) -> HistoricalCloseSeries:
    """One bounded child request; on failure report a structured, redacted reason."""
    if source not in PROVIDERS:
        raise ValueError("unknown provider")
    subject.prefixed
    validate_window(start, end, datetime.now(SH))
    try:
        proc = subprocess.run([sys.executable, "-m", __name__, "--child", source, subject.symbol,
            subject.asset_type, start.isoformat(), end.isoformat()],
            capture_output=True, check=False, timeout=CHILD_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("WATCHDOG_TIMEOUT") from exc
    if proc.returncode or len(proc.stdout) > MAX_CHILD_BYTES:
        raise ValueError("CHILD_EXIT_OR_OUTPUT_LIMIT")
    try:
        response = json.loads(proc.stdout)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("CHILD_RECEIPT_INVALID") from exc
    if response.get("status") != "OBSERVED":
        stage, kind = response.get("stage"), response.get("error_type")
        if stage not in {"REQUEST_VALIDATION", "PROVIDER_FETCH", "NORMALIZED_VALIDATION"}:
            raise ValueError("CHILD_RECEIPT_INVALID")
        if not isinstance(kind, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,59}", kind):
            raise ValueError("CHILD_RECEIPT_INVALID")
        raise ValueError(f"{stage}:{kind}")
    series = HistoricalCloseSeries.model_validate_json(json.dumps(response["series"]))
    if (series.subject_id != subject.symbol or series.source_label != source
            or series.price_basis != "RAW_CLOSE" or series.currency != "CNY"):
        raise ValueError("CHILD_IDENTITY_MISMATCH")
    return _from_rows([[x.session.isoformat(), x.close] for x in series.closes],
                      subject, source, start, end)


def sources_agree(left: tuple[HistoricalCloseSeries, HistoricalCloseSeries],
                  right: tuple[HistoricalCloseSeries, HistoricalCloseSeries]) -> bool:
    """Compare exact date sets and vendor price differences, not source independence."""
    return all(
        series_a.subject_id == series_b.subject_id
        and series_a.price_basis == series_b.price_basis
        and series_a.currency == series_b.currency
        and tuple(x.session for x in series_a.closes) == tuple(x.session for x in series_b.closes)
        and all(abs(x.close-y.close) / max(x.close, y.close) <= 0.001
                for x, y in zip(series_a.closes, series_b.closes))
        for series_a, series_b in zip(left, right)
    )


def observe_pair(candidate: PublicSecurity, alternative: PublicSecurity, start: date, end: date,
                 *, providers: tuple[str, ...] = PROVIDERS) -> tuple[dict, tuple]:
    """Use all bounded source attempts; report source conflicts, never silently merge."""
    validate_window(start, end, datetime.now(SH))
    if candidate.symbol == alternative.symbol or not providers or len(set(providers)) != len(providers):
        raise ValueError("invalid pair or provider list")
    candidate.prefixed
    alternative.prefixed
    found = []
    failures = []
    for source in providers:
        if source not in PROVIDERS:
            raise ValueError("unknown provider")
        result = []
        for subject in (candidate, alternative):
            try:
                result.append(acquire_series(source, subject, start, end))
            except (ValueError, OSError) as exc:
                failures.append({"provider": source, "asset_type": subject.asset_type,
                    "error_code": str(exc)[:100] if type(exc) is ValueError and re.fullmatch(r"[A-Za-z0-9_:]{1,100}", str(exc))
                    else type(exc).__name__})
        if len(result) != 2:
            continue
        try:
            ref = historical_pair_reference(*result, last_completed_session=end)
        except ValueError:
            failures.append({"provider": source, "error_code": "DATE_OR_PRICE_ALIGNMENT"})
            continue
        found.append((source, tuple(result), ref))
    if not found:
        return {"status": "BLOCKED", "failures": failures, "decision_authority": False}, ()
    primary, primary_series, ref = found[0]
    crosscheck = "SINGLE_SOURCE" if len(found) == 1 else (
        "MATCH" if all(sources_agree(primary_series, other) for _, other, _ in found[1:]) else "CONFLICT")
    summary = {"status": "OBSERVED_REFERENCE_ONLY", "observed_at": datetime.now(SH).isoformat(),
        "primary_provider": primary, "providers": [x[0] for x in found], "crosscheck": crosscheck,
        "failures": failures, "reference": ref.model_dump(mode="json"), "raw_provider_bytes_retained": False}
    return summary, tuple((source, pair) for source, pair, _ in found)


if __name__ == "__main__":
    # Python -m runs this module as __main__; acquire_series is invoked by
    # importers, never recursively by the child.
    if len(sys.argv) != 7 or sys.argv[1] != "--child":
        raise SystemExit(2)
    _child(*sys.argv[2:])
