"""Content-addressed normalized historical observations, not source admission.

A caller supplies an explicit local directory. Reopen and rehash the actual
normalized receipt bytes; recompute the output from observations, never trust
a stored summary. No credentials, trading, or raw provider HTTP-body archive.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .historical_capture import PROVIDERS, PublicSecurity, summarize_observed_pair, validate_window
from .historical_reference import HistoricalCloseSeries
from .holding_risk import (
    CashDistributionInputs,
    ShareCashDistributionInputs,
    holding_period_reference,
)
from .market_calendar import CalendarObservation

MAX_BYTES = 2 * 1024 * 1024
MAX_CAPTURES_PER_PAIR_DAY = 128


class HistoricalCaptureFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    provider: Literal["sina", "baostock", "tencent", "eastmoney"]
    asset_type: Literal["STOCK", "ETF"]
    error_code: str = Field(pattern=r"^[A-Za-z0-9_:]{1,160}$")


class HistoricalReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal["1", "2", "3"] = "1"
    acquisition_method: Literal["BOUNDED_VENDOR_NORMALIZED_CLOSE_V1"] = "BOUNDED_VENDOR_NORMALIZED_CLOSE_V1"
    candidate: PublicSecurity
    alternative: PublicSecurity
    first_requested: date
    last_completed: date
    observed_at: AwareDatetime
    akshare_version: str = Field(min_length=1, max_length=100)
    attempted_providers: tuple[str, ...] = Field(min_length=1, max_length=4)
    failures: tuple[HistoricalCaptureFailure, ...] = Field(default=(), max_length=8)
    series: tuple[HistoricalCloseSeries, ...] = Field(max_length=8)
    calendar: CalendarObservation | None = None
    calendar_error_code: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_:]{1,160}$")
    distributions: CashDistributionInputs | None = None
    share_cash_distributions: ShareCashDistributionInputs | None = None
    raw_provider_bytes_retained: Literal[False] = False
    research_only: Literal[True] = True
    execution_allowed: Literal[False] = False


def _bytes(receipt: HistoricalReceipt) -> bytes:
    payload=receipt.model_dump(mode="json")
    # Exact v1/v2 serialization must remain byte-for-byte compatible.
    if receipt.schema_version in {"1", "2"}:
        payload.pop("share_cash_distributions")
    if receipt.schema_version=="1":
        for key in ("calendar","calendar_error_code","distributions"):
            payload.pop(key)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _read(path: Path) -> bytes:
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("missing or oversized historical observation")
    with path.open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("oversized historical observation")
    return data


def _summary(receipt: HistoricalReceipt) -> dict:
    validate_window(receipt.first_requested, receipt.last_completed, receipt.observed_at)
    if receipt.schema_version=="1" and any(x is not None for x in (receipt.calendar,receipt.calendar_error_code,receipt.distributions)):
        raise ValueError("version one cannot carry holding-risk inputs")
    if receipt.schema_version in {"2", "3"} and (receipt.calendar is None)==(receipt.calendar_error_code is None):
        raise ValueError("version two or three requires one calendar outcome")
    if receipt.schema_version in {"1", "2"} and receipt.share_cash_distributions is not None:
        raise ValueError("legacy receipt cannot carry share/cash distribution terms")
    if receipt.schema_version == "3" and (receipt.distributions is not None
            or receipt.share_cash_distributions is None or not receipt.share_cash_distributions.events):
        raise ValueError("version three requires explicit nonempty combined terms without legacy cash terms")
    if (len(set(receipt.attempted_providers)) != len(receipt.attempted_providers)
            or any(provider not in PROVIDERS for provider in receipt.attempted_providers)):
        raise ValueError("invalid attempted provider scope")
    # This receipt currently supports the product's stock-vs-ETF reference.
    # Distinct asset classes make a per-provider/asset coverage record unambiguous.
    if (receipt.candidate.asset_type, receipt.alternative.asset_type) != ("STOCK", "ETF"):
        raise ValueError("receipt requires stock candidate and ETF alternative")
    expected = {(p, asset) for p in receipt.attempted_providers for asset in ("STOCK", "ETF")
                if p != "baostock" or asset == "STOCK"}
    kinds = {receipt.candidate.symbol: "STOCK", receipt.alternative.symbol: "ETF"}
    successes = [(series.source_label, kinds.get(series.subject_id)) for series in receipt.series]
    failures = [(failure.provider, failure.asset_type) for failure in receipt.failures]
    observed = successes + failures
    if len(set(observed)) != len(observed) or set(observed) != expected:
        raise ValueError("incomplete or contradictory source attempt coverage")
    result = summarize_observed_pair(receipt.candidate, receipt.alternative, receipt.series,
                                     receipt.first_requested, receipt.last_completed)
    result = result | {"attempted_providers": list(receipt.attempted_providers),
                       "failures": [failure.model_dump(mode="json") for failure in receipt.failures]}
    if receipt.schema_version=="1":
        return result
    # Preserve the raw-price reference and report an independent holding-risk
    # blocker. Do not fabricate trading sessions or silently drop price dates.
    result["holding_reference"]={"status":"BLOCKED","error_code":receipt.calendar_error_code or "PRICE_PAIR_UNAVAILABLE"}
    if receipt.calendar is not None and result["status"]=="OBSERVED_REFERENCE_ONLY":
        left=next(s for s in receipt.series if s.subject_id==receipt.candidate.symbol)
        right=next(s for s in receipt.series if s.subject_id==receipt.alternative.symbol)
        try:
            result["holding_reference"]=holding_period_reference(left,right,receipt.calendar,
                first=receipt.first_requested,last=receipt.last_completed,cutoff=receipt.observed_at,
                distributions=receipt.distributions, share_cash_distributions=receipt.share_cash_distributions)
        except (ValueError,ArithmeticError) as exc:
            code=str(exc)
            if not code.isascii() or not code.isupper() or not code.replace("_","").isalnum():
                code="HOLDING_REFERENCE_INPUT_INVALID"
            result["holding_reference"]={"status":"BLOCKED","error_code":code[:120]}
    return result


def persist_receipt(directory: Path, receipt: HistoricalReceipt) -> tuple[str, dict]:
    """Explicit local write only; even conflicts remain inspectable, never displayed as facts."""
    receipt = HistoricalReceipt.model_validate(receipt.model_dump())
    result = _summary(receipt)
    raw = _bytes(receipt)
    if len(raw) > MAX_BYTES:
        raise ValueError("receipt too large")
    digest = hashlib.sha256(raw).hexdigest()
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    folder = folder.resolve(strict=True)
    path = folder / (digest + ".json")
    if not path.resolve().is_relative_to(folder):
        raise ValueError("receipt path escape")
    if not path.exists():
        for count, _entry in enumerate(folder.iterdir(), start=1):
            if count >= MAX_CAPTURES_PER_PAIR_DAY:
                raise ValueError("capture bound exceeded")
        fd, temp = tempfile.mkstemp(prefix=".capture-", dir=folder)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp, path)
            except FileExistsError:
                pass
        finally:
            os.unlink(temp)
    if _read(path) != raw:
        raise ValueError("stored normalized observation mismatch")
    return digest, result


def load_receipt(directory: Path, candidate: PublicSecurity, alternative: PublicSecurity,
                   end: date, *, now: datetime) -> dict:
    """Read/recompute the newest exact pair/day receipt. No fallback after corruption."""
    if now.utcoffset() is None:
        raise ValueError("invalid research cutoff")
    candidate.prefixed
    alternative.prefixed
    if candidate.symbol == alternative.symbol:
        raise ValueError("self comparison")
    folder = Path(directory)
    if not folder.is_dir():
        return {"status": "UNAVAILABLE", "error_code": "NO_LOCAL_EXACT_PAIR_OBSERVATION"}
    receipts = []
    for count, path in enumerate(folder.iterdir()):
        if count >= MAX_CAPTURES_PER_PAIR_DAY:
            raise ValueError("capture bound exceeded")
        if not re.fullmatch(r"[0-9a-f]{64}\.json", path.name):
            continue
        if not path.resolve().is_relative_to(folder.resolve(strict=True)):
            raise ValueError("receipt path escape")
        raw = _read(path)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != path.stem:
            raise ValueError("normalized observation digest mismatch")
        receipt = HistoricalReceipt.model_validate_json(raw)
        if (_bytes(receipt) != raw or receipt.candidate != candidate or receipt.alternative != alternative
                or receipt.last_completed != end or receipt.observed_at > now):
            raise ValueError("normalized observation identity/time mismatch")
        receipts.append((receipt.observed_at, digest, receipt))
    if not receipts:
        return {"status": "UNAVAILABLE", "error_code": "NO_LOCAL_EXACT_PAIR_OBSERVATION"}
    stamp, digest, receipt = max(receipts, key=lambda item: (item[0], item[1]))
    result = _summary(receipt)
    return result | {"observed_at": stamp.isoformat(),
        "normalized_observation_sha256": digest, "normalized_observation_rehashed": True}


