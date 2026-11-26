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
from itertools import combinations
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from .historical_reference import DailyClose, HistoricalCloseSeries, historical_pair_reference

SH = ZoneInfo("Asia/Shanghai")
PROVIDERS = ("sina", "baostock", "tencent", "eastmoney")
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
        raise ValueError("CLOSE_ROW_COUNT_INVALID")
    if len(rows) < 21:
        raise ValueError("INSUFFICIENT_CLOSE_ROWS")
    parsed = []
    for item in rows:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise ValueError("CLOSE_ROW_SCHEMA_INVALID")
        day = date.fromisoformat(item[0])
        if not start <= day <= end or day.weekday() >= 5:
            raise ValueError("CLOSE_DATE_OUTSIDE_WINDOW")
        if isinstance(item[1], bool):
            raise ValueError("CLOSE_PRICE_BOOLEAN")
        parsed.append(DailyClose(session=day, close=float(item[1])))
    parsed.sort(key=lambda item: item.session)
    if len({item.session for item in parsed}) != len(parsed):
        raise ValueError("DUPLICATE_CLOSE_SESSION")
    series = HistoricalCloseSeries(subject_id=subject.symbol, currency="CNY",
        price_basis="RAW_CLOSE", source_label=provider, closes=tuple(parsed))
    if series.closes[-1].session != end:
        raise ValueError("TERMINAL_SESSION_MISSING")
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
        # Some responses contain the full available interval despite the date
        # query; clip only by explicit date, never by row count or current quote.
        rows = block["day"]
        if any(not isinstance(row, list) or len(row) < 3 for row in rows):
            raise ValueError("TENCENT_ROW_SCHEMA_INVALID")
        return [[row[0], row[2]] for row in rows if start <= date.fromisoformat(row[0]) <= end]
    if source == "baostock":
        if subject.asset_type != "STOCK":
            raise ValueError("BAOSTOCK_STOCK_ONLY")
        import baostock as bs

        login = bs.login()
        if login.error_code != "0":
            raise ValueError("BAOSTOCK_LOGIN_FAILED")
        try:
            code = prefixed[:2] + "." + prefixed[2:]
            result = bs.query_history_k_data_plus(code, "date,code,close,adjustflag,tradestatus",
                start_date=start.isoformat(), end_date=end.isoformat(), frequency="d", adjustflag="3")
            if result.error_code != "0":
                raise ValueError("BAOSTOCK_QUERY_FAILED")
            rows = []
            while result.next():
                day, identity, close, adjustment, trading = result.get_row_data()
                if identity != code or adjustment != "3":
                    raise ValueError("BAOSTOCK_IDENTITY_OR_ADJUSTMENT")
                # Suspended rows cannot be treated as observed closing trades.
                if trading == "1":
                    rows.append([day, close])
                elif trading != "0":
                    raise ValueError("BAOSTOCK_TRADING_STATE_UNKNOWN")
            if result.error_code != "0":
                raise ValueError("BAOSTOCK_QUERY_FAILED")
            return rows
        finally:
            bs.logout()
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
        detail = type(exc).__name__
        if isinstance(exc, AttributeError) and isinstance(exc.name, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,59}", exc.name):
            detail += ":" + exc.name
        elif type(exc) is ValueError and re.fullmatch(r"[A-Z0-9_]{3,60}", str(exc)):
            detail += ":" + str(exc)
        print(json.dumps({"status": "BLOCKED", "stage": stage, "error_type": detail}))


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
    if not isinstance(response, dict):
        raise ValueError("CHILD_RECEIPT_INVALID")
    if response.get("status") != "OBSERVED":
        stage, kind = response.get("stage"), response.get("error_type")
        if stage not in {"REQUEST_VALIDATION", "PROVIDER_FETCH", "NORMALIZED_VALIDATION"}:
            raise ValueError("CHILD_RECEIPT_INVALID")
        if not isinstance(kind, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_:]{0,119}", kind):
            raise ValueError("CHILD_RECEIPT_INVALID")
        raise ValueError(f"{stage}:{kind}")
    series = HistoricalCloseSeries.model_validate_json(json.dumps(response["series"]))
    if (series.subject_id != subject.symbol or series.source_label != source
            or series.price_basis != "RAW_CLOSE" or series.currency != "CNY"):
        raise ValueError("CHILD_IDENTITY_MISMATCH")
    return _from_rows([[x.session.isoformat(), x.close] for x in series.closes],
                      subject, source, start, end)


def sources_agree(series_a: HistoricalCloseSeries, series_b: HistoricalCloseSeries) -> bool:
    """Compare one subject's exact date sets and vendor price differences."""
    return (
        series_a.subject_id == series_b.subject_id
        and series_a.price_basis == series_b.price_basis
        and series_a.currency == series_b.currency
        and tuple(x.session for x in series_a.closes) == tuple(x.session for x in series_b.closes)
        and all(abs(x.close-y.close) / max(x.close, y.close) <= 0.001
                for x, y in zip(series_a.closes, series_b.closes))
    )


def summarize_observed_pair(candidate: PublicSecurity, alternative: PublicSecurity,
                            observed: tuple[HistoricalCloseSeries, ...], start: date, end: date) -> dict:
    """Recompute exact source identity, crosschecks and statistics without I/O.

    Distinct providers may cover the two assets. No mixed dates, source conflicts
    or single-source observations are promoted to decision-grade evidence.
    """
    candidate.prefixed
    alternative.prefixed
    if candidate.symbol == alternative.symbol:
        raise ValueError("SELF_COMPARISON")
    groups = {candidate.symbol: [], alternative.symbol: []}
    seen = set()
    for source in observed:
        if source.subject_id not in groups or source.source_label not in PROVIDERS:
            raise ValueError("OBSERVED_SOURCE_IDENTITY")
        subject = candidate if source.subject_id == candidate.symbol else alternative
        if source.source_label == "baostock" and subject.asset_type != "STOCK":
            raise ValueError("BAOSTOCK_STOCK_ONLY")
        key = (source.subject_id, source.source_label)
        if key in seen:
            raise ValueError("DUPLICATE_OBSERVED_SOURCE")
        seen.add(key)
        if source.currency != "CNY" or source.price_basis != "RAW_CLOSE":
            raise ValueError("OBSERVED_SOURCE_PRICE_BASIS")
        normalized = _from_rows([[x.session.isoformat(), x.close] for x in source.closes],
            subject, source.source_label, start, end)
        if normalized != source:
            raise ValueError("OBSERVED_SOURCE_NOT_CANONICAL")
        groups[source.subject_id].append(source)
    left, right = groups[candidate.symbol], groups[alternative.symbol]
    summary = {"candidate_providers": [x.source_label for x in left],
        "alternative_providers": [x.source_label for x in right], "decision_authority": False,
        "research_only": True, "execution_allowed": False, "raw_provider_bytes_retained": False}
    if not left or not right:
        return summary | {"status": "BLOCKED", "error_code": "MISSING_ASSET_HISTORY"}
    if any(not sources_agree(a, b) for group in (left, right) for a, b in combinations(group, 2)):
        return summary | {"status": "BLOCKED", "crosscheck": "CONFLICT", "error_code": "SOURCE_CONFLICT"}
    try:
        ref = historical_pair_reference(left[0], right[0], last_completed_session=end)
    except ValueError:
        return summary | {"status": "BLOCKED", "error_code": "DATE_OR_PRICE_ALIGNMENT"}
    crosscheck = ("MATCH" if len(left) > 1 and len(right) > 1
                  else "PARTIAL_CROSSCHECK" if len(left) > 1 or len(right) > 1
                  else "SINGLE_SOURCE_PER_ASSET")
    return summary | {"status": "OBSERVED_REFERENCE_ONLY", "crosscheck": crosscheck,
                      "reference": ref.model_dump(mode="json")}


def observe_pair(candidate: PublicSecurity, alternative: PublicSecurity, start: date, end: date,
                 *, providers: tuple[str, ...] = PROVIDERS) -> tuple[dict, tuple[HistoricalCloseSeries, ...]]:
    """Collect bounded source attempts per asset; retain failures, never merge dates."""
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
        for subject in (candidate, alternative):
            if source == "baostock" and subject.asset_type != "STOCK":
                continue
            try:
                found.append(acquire_series(source, subject, start, end))
            except (ValueError, OSError) as exc:
                failures.append({"provider": source, "asset_type": subject.asset_type,
                    "error_code": str(exc)[:160] if type(exc) is ValueError and re.fullmatch(r"[A-Za-z0-9_:]{1,160}", str(exc))
                    else type(exc).__name__})
    summary = summarize_observed_pair(candidate, alternative, tuple(found), start, end)
    summary.update(observed_at=datetime.now(SH).isoformat(), failures=failures,
                   attempted_providers=list(providers))
    return summary, tuple(found)


if __name__ == "__main__":
    # Python -m runs this module as __main__; acquire_series is invoked by
    # importers, never recursively by the child.
    if len(sys.argv) != 7 or sys.argv[1] != "--child":
        raise SystemExit(2)
    _child(*sys.argv[2:])
