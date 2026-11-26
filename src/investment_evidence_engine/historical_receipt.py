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

from .historical_capture import PublicSecurity, summarize_observed_pair, validate_window
from .historical_reference import HistoricalCloseSeries

MAX_BYTES = 2 * 1024 * 1024
MAX_CAPTURES_PER_PAIR_DAY = 128


class HistoricalReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal["1"] = "1"
    acquisition_method: Literal["BOUNDED_VENDOR_NORMALIZED_CLOSE_V1"] = "BOUNDED_VENDOR_NORMALIZED_CLOSE_V1"
    candidate: PublicSecurity
    alternative: PublicSecurity
    first_requested: date
    last_completed: date
    observed_at: AwareDatetime
    akshare_version: str = Field(min_length=1, max_length=100)
    series: tuple[HistoricalCloseSeries, ...] = Field(min_length=1, max_length=8)
    raw_provider_bytes_retained: Literal[False] = False
    research_only: Literal[True] = True
    execution_allowed: Literal[False] = False


def _bytes(receipt: HistoricalReceipt) -> bytes:
    return json.dumps(receipt.model_dump(mode="json"), ensure_ascii=False,
                      sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


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
    return summarize_observed_pair(receipt.candidate, receipt.alternative, receipt.series,
                                  receipt.first_requested, receipt.last_completed)


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
        if len(list(folder.iterdir())) >= MAX_CAPTURES_PER_PAIR_DAY:
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


