"""Immutable normalized quote receipt retaining exact vendor wire bytes locally.

No brokerage credentials, orders, private account data or upload are involved.
Both fixed providers must have an explicit success or sanitized failure.
An observation is re-parsed from raw bytes at every read, and the latest
receipt is selected even if both attempts failed. No stale fallback.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .book_depth import compare_displayed_depth, depth_walk_scenario
from .historical_capture import SH, PublicSecurity
from .quote_reference import (
    MAX_BYTES,
    PROVIDERS,
    acquire_quote,
    crosscheck_quotes,
    parse_quote,
    quote_reference,
)

MAX_RECEIPT_BYTES = 256*1024
MAX_PER_SUBJECT_DAY = 256
CHILD_TIMEOUT_SECONDS = 18


class QuotePayload(BaseModel):
    model_config = ConfigDict(extra="forbid",frozen=True,strict=True)
    provider: Literal["tencent","sina"]
    observed_at: AwareDatetime
    raw_base64: str = Field(min_length=4,max_length=4*((MAX_BYTES+2)//3))
    raw_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    def raw(self) -> bytes:
        data=base64.b64decode(self.raw_base64,validate=True)
        if not data or len(data)>MAX_BYTES or hashlib.sha256(data).hexdigest()!=self.raw_sha256:
            raise ValueError("QUOTE_RAW_BYTES_HASH_MISMATCH")
        if base64.b64encode(data).decode("ascii")!=self.raw_base64:
            raise ValueError("QUOTE_RAW_BYTES_NOT_CANONICAL")
        return data


class QuoteFailure(BaseModel):
    model_config = ConfigDict(extra="forbid",frozen=True,strict=True)
    provider: Literal["tencent","sina"]
    error_code: str = Field(pattern=r"^[A-Za-z0-9_:]{1,120}$")


class QuoteReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid",frozen=True,strict=True)
    schema_version: Literal["1"] = "1"
    subject: PublicSecurity
    captured_at: AwareDatetime
    payloads: tuple[QuotePayload,...] = Field(max_length=2)
    failures: tuple[QuoteFailure,...] = Field(max_length=2)
    decision_authority: Literal[False] = False


def _bytes(receipt: QuoteReceipt) -> bytes:
    return json.dumps(receipt.model_dump(mode="json"),sort_keys=True,separators=(",",":"),
        ensure_ascii=False,allow_nan=False).encode("utf-8")


def summarize_receipt(receipt: QuoteReceipt,*,now: datetime) -> dict:
    receipt=QuoteReceipt.model_validate(receipt.model_dump())
    receipt.subject.prefixed
    if now.utcoffset() is None or receipt.captured_at>now:
        raise ValueError("QUOTE_RECEIPT_CHRONOLOGY_INVALID")
    attempted=[item.provider for item in (*receipt.payloads,*receipt.failures)]
    if len(attempted)!=len(set(attempted)) or set(attempted)!=set(PROVIDERS):
        raise ValueError("QUOTE_ATTEMPT_COVERAGE_INVALID")
    obs=[]
    for payload in receipt.payloads:
        if payload.observed_at>receipt.captured_at:
            raise ValueError("QUOTE_PAYLOAD_AFTER_RECEIPT")
        obs.append(parse_quote(payload.raw(),receipt.subject,payload.provider,payload.observed_at))
    rows=[quote_reference(q,now=now) for q in obs]
    usable=[row for row in rows if row["status"]=="OBSERVED_TOP_OF_BOOK_ONLY"]
    comparison=crosscheck_quotes(*obs,now=now) if len(obs)==2 else {"status":"SOURCE_UNAVAILABLE"}
    depth={"status":"UNAVAILABLE","error_code":"DEPTH_REQUIRES_BOTH_SOURCES"}
    if len(obs)==2:
        payloads={p.provider:p for p in receipt.payloads}
        t,s=payloads["tencent"],payloads["sina"]
        depth=compare_displayed_depth(receipt.subject,t.raw(),t.observed_at,s.raw(),s.observed_at,now=now)
    return {"status":"OBSERVED_TOP_OF_BOOK_ONLY" if usable else "UNAVAILABLE",
        "subject":receipt.subject.model_dump(mode="json"),"captured_at":receipt.captured_at.isoformat(),
        "observations":rows,"crosscheck":comparison,"displayed_depth":depth,
        "failures":[f.model_dump(mode="json") for f in receipt.failures],
        "raw_payloads_rehashed":True,"impact_cost_estimated":False,
        "formal_liquidity_cost_estimated":False,"decision_authority":False,
        "research_only":True,"execution_allowed":False}


def _read(path: Path) -> bytes:
    if not path.is_file() or path.stat().st_size>MAX_RECEIPT_BYTES:
        raise ValueError("QUOTE_RECEIPT_SIZE_OR_PATH_INVALID")
    with path.open("rb") as handle:
        raw=handle.read(MAX_RECEIPT_BYTES+1)
    if len(raw)>MAX_RECEIPT_BYTES:
        raise ValueError("QUOTE_RECEIPT_TOO_LARGE")
    return raw


def persist_quote_receipt(folder: Path,receipt: QuoteReceipt) -> tuple[str,dict]:
    receipt=QuoteReceipt.model_validate(receipt.model_dump())
    result=summarize_receipt(receipt,now=receipt.captured_at)
    data=_bytes(receipt)
    if len(data)>MAX_RECEIPT_BYTES:
        raise ValueError("QUOTE_RECEIPT_TOO_LARGE")
    digest=hashlib.sha256(data).hexdigest()
    folder.mkdir(parents=True,exist_ok=True)
    base=folder.resolve(strict=True)
    path=base/(digest+".json")
    if not path.resolve().is_relative_to(base):
        raise ValueError("QUOTE_RECEIPT_PATH_ESCAPE")
    if not path.exists():
        for n,_ in enumerate(base.iterdir(),start=1):
            if n>=MAX_PER_SUBJECT_DAY:
                raise ValueError("QUOTE_RECEIPT_COUNT_LIMIT")
        fd,temp=tempfile.mkstemp(prefix=".quote-",dir=base)
        try:
            with os.fdopen(fd,"wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp,path)
            except FileExistsError:
                pass
        finally:
            os.unlink(temp)
    if _read(path)!=data:
        raise ValueError("QUOTE_RECEIPT_PERSIST_MISMATCH")
    return digest,result


def read_latest_quote_receipt(folder: Path,subject: PublicSecurity,*,now: datetime) -> tuple[QuoteReceipt,str] | None:
    if now.utcoffset() is None:
        raise ValueError("QUOTE_READ_TIME_INVALID")
    subject.prefixed
    if not folder.is_dir():
        return None
    base=folder.resolve(strict=True)
    rows=[]
    for n,path in enumerate(base.iterdir(),start=1):
        if n>MAX_PER_SUBJECT_DAY:
            raise ValueError("QUOTE_RECEIPT_COUNT_LIMIT")
        if not re.fullmatch(r"[0-9a-f]{64}\.json",path.name):
            continue
        if not path.resolve(strict=True).is_relative_to(base):
            raise ValueError("QUOTE_RECEIPT_PATH_ESCAPE")
        data=_read(path)
        if hashlib.sha256(data).hexdigest()!=path.stem:
            raise ValueError("QUOTE_RECEIPT_HASH_MISMATCH")
        receipt=QuoteReceipt.model_validate_json(data)
        if (_bytes(receipt)!=data or receipt.subject!=subject or receipt.captured_at>now
                or receipt.captured_at.astimezone(SH).date()!=now.astimezone(SH).date()):
            raise ValueError("QUOTE_RECEIPT_SCOPE_MISMATCH")
        # Even older corrupted payloads must not disappear behind a new capture.
        summarize_receipt(receipt,now=receipt.captured_at)
        rows.append((receipt.captured_at,path.stem,receipt))
    if not rows:
        return {"status":"UNAVAILABLE","error_code":"NO_LOCAL_QUOTE_RECEIPT"}
    _,digest,receipt=max(rows,key=lambda row:(row[0],row[1]))
    return receipt,digest


def load_latest_quote(folder: Path,subject: PublicSecurity,*,now: datetime) -> dict:
    selected=read_latest_quote_receipt(folder,subject,now=now)
    if selected is None:
        return {"status":"UNAVAILABLE","error_code":"NO_LOCAL_QUOTE_RECEIPT"}
    receipt,digest=selected
    return summarize_receipt(receipt,now=now) | {"receipt_sha256":digest,"receipt_rehashed":True}


def walk_latest_quote(folder: Path,subject: PublicSecurity,*,now: datetime,side: str,units: int) -> dict:
    if type(units) is not int or not 0<units<=100000000 or side not in {"BUY","SELL"}:
        raise ValueError("DEPTH_SCENARIO_SIZE_OR_SIDE_INVALID")
    selected=read_latest_quote_receipt(folder,subject,now=now)
    if selected is None:
        return {"status":"UNAVAILABLE","error_code":"NO_LOCAL_QUOTE_RECEIPT"}
    receipt,digest=selected
    payloads={p.provider:p for p in receipt.payloads}
    if set(payloads)!=set(PROVIDERS):
        return {"status":"UNAVAILABLE","error_code":"DEPTH_REQUIRES_BOTH_SOURCES","receipt_sha256":digest}
    t,s=payloads["tencent"],payloads["sina"]
    return depth_walk_scenario(subject,t.raw(),t.observed_at,s.raw(),s.observed_at,
        now=now,side=side,units=units) | {"receipt_sha256":digest,"receipt_rehashed":True}


def _child(provider: str,symbol: str,asset_type: str) -> None:
    try:
        subject=PublicSecurity(symbol=symbol,asset_type=asset_type)
        raw,obs=acquire_quote(subject,provider)
        payload=QuotePayload(provider=provider,observed_at=obs.observed_at,
            raw_base64=base64.b64encode(raw).decode("ascii"),raw_sha256=obs.raw_response_sha256)
        print(json.dumps({"status":"OBSERVED","payload":payload.model_dump(mode="json")}))
    except Exception as exc:
        code=str(exc)
        if not re.fullmatch(r"[A-Z0-9_]{1,100}",code):
            code=type(exc).__name__
        print(json.dumps({"status":"BLOCKED","error_code":code}))


def capture_quotes(subject: PublicSecurity) -> QuoteReceipt:
    subject.prefixed
    payloads=[]
    failures=[]
    for provider in PROVIDERS:
        try:
            proc=subprocess.run([sys.executable,"-m",__name__,"--child",provider,subject.symbol,subject.asset_type],
                                capture_output=True,check=False,timeout=CHILD_TIMEOUT_SECONDS)
            if proc.returncode or len(proc.stdout)>MAX_RECEIPT_BYTES:
                raise ValueError("QUOTE_CHILD_EXIT_OR_OUTPUT_LIMIT")
            data=json.loads(proc.stdout)
            if not isinstance(data,dict):
                raise ValueError("QUOTE_CHILD_SCHEMA_INVALID")
            if data.get("status")!="OBSERVED":
                error=data.get("error_code")
                raise ValueError(error if isinstance(error,str) and re.fullmatch(r"[A-Za-z0-9_]{1,100}",error)
                                 else "QUOTE_CHILD_BLOCKED")
            payload=QuotePayload.model_validate_json(json.dumps(data["payload"]))
            if payload.provider!=provider:
                raise ValueError("QUOTE_CHILD_PROVIDER_MISMATCH")
            parse_quote(payload.raw(),subject,provider,payload.observed_at)
            payloads.append(payload)
        except subprocess.TimeoutExpired:
            failures.append(QuoteFailure(provider=provider,error_code="QUOTE_WATCHDOG_TIMEOUT"))
        except (ValueError,OSError,KeyError,TypeError) as exc:
            code=str(exc)
            failures.append(QuoteFailure(provider=provider,error_code=code if re.fullmatch(r"[A-Za-z0-9_]{1,100}",code)
                                         else type(exc).__name__))
    return QuoteReceipt(subject=subject,captured_at=datetime.now(SH),
                        payloads=tuple(payloads),failures=tuple(failures))


if __name__=="__main__":
    if len(sys.argv)!=5 or sys.argv[1]!="--child":
        raise SystemExit(2)
    _child(*sys.argv[2:])
