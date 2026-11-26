"""Bind a conditional scenario to observed normalized pair bytes.

A stored receipt freezes assumptions, not facts or predictions. Reading always
rederives arithmetic and requires the same current local historical pair hash.
No public upload, private account, automatic refresh or admission.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from .historical_capture import PublicSecurity
from .historical_receipt import HistoricalReceipt, load_receipt
from .historical_receipt import _bytes as historical_bytes
from .joint_scenarios import MODEL_VERSION, JointAssumptions, PairPriceAnchor, joint_scenarios

MAX_PAIR_BYTES = 2*1024*1024
MAX_SCENARIO_BYTES = 256*1024
MAX_SCENARIO_RECEIPTS = 32


def _read(path: Path,limit: int) -> bytes:
    if not path.is_file() or path.stat().st_size>limit:
        raise ValueError("JOINT_RECEIPT_PATH_OR_SIZE_INVALID")
    with path.open("rb") as handle:
        data=handle.read(limit+1)
    if len(data)>limit:
        raise ValueError("JOINT_RECEIPT_SIZE_LIMIT")
    return data


def load_pair_anchor(folder: Path,stock: PublicSecurity,etf: PublicSecurity,end: date,*,now: datetime) -> PairPriceAnchor:
    result=load_receipt(folder,stock,etf,end,now=now)
    if (result.get("status")!="OBSERVED_REFERENCE_ONLY" or result.get("crosscheck")!="MATCH"
            or (result.get("holding_reference") or {}).get("status")!="HISTORICAL_HOLDING_REFERENCE_ONLY"):
        raise ValueError("JOINT_COMPLETE_DUAL_SOURCE_PAIR_REQUIRED")
    digest=result["normalized_observation_sha256"]
    if not re.fullmatch(r"[a-f0-9]{64}",digest):
        raise ValueError("JOINT_PAIR_DIGEST_INVALID")
    base=folder.resolve(strict=True)
    path=base/(digest+".json")
    if not path.resolve(strict=True).is_relative_to(base):
        raise ValueError("JOINT_PAIR_PATH_ESCAPE")
    raw=_read(path,MAX_PAIR_BYTES)
    if hashlib.sha256(raw).hexdigest()!=digest:
        raise ValueError("JOINT_PAIR_BYTES_CHANGED")
    pair=HistoricalReceipt.model_validate_json(raw)
    if (historical_bytes(pair)!=raw or pair.calendar is None
            or (pair.candidate,pair.alternative,pair.last_completed)!=(stock,etf,end)
            or pair.observed_at>now):
        raise ValueError("JOINT_PAIR_SCOPE_MISMATCH")
    prices=[]
    for subject in (stock,etf):
        series=[s for s in pair.series if s.subject_id==subject.symbol]
        if len({s.source_label for s in series})<2 or any(
                s.price_basis!="RAW_CLOSE" or s.currency!="CNY" or s.closes[-1].session!=end for s in series):
            raise ValueError("JOINT_TERMINAL_PRICE_SOURCE_REQUIRED")
        exact={s.closes[-1].close for s in series}
        if len(exact)!=1:
            # The historical tolerance is suitable for a descriptive return
            # reference, not an exact cent/tick-based entry cost calculation.
            raise ValueError("JOINT_TERMINAL_CLOSE_NOT_EXACT")
        prices.append(exact.pop())
    return PairPriceAnchor(stock=stock,etf=etf,reference_session=end,stock_raw_close_cny=prices[0],
        etf_raw_close_cny=prices[1],observed_at=pair.observed_at,normalized_pair_sha256=digest)


class JointScenarioReceipt(BaseModel):
    model_config=ConfigDict(extra="forbid",frozen=True,strict=True)
    schema_version: Literal["1"]="1"
    model_version: Literal["JOINT_CASH_ALTERNATIVES_V1"]=MODEL_VERSION
    anchor: PairPriceAnchor
    assumptions: JointAssumptions
    recorded_at: AwareDatetime
    expires_at: AwareDatetime
    decision_authority: Literal[False]=False


def _bytes(receipt: JointScenarioReceipt) -> bytes:
    return json.dumps(receipt.model_dump(mode="json"),sort_keys=True,separators=(",",":"),
        ensure_ascii=False,allow_nan=False).encode("utf-8")


def rederive(receipt: JointScenarioReceipt) -> dict:
    receipt=JointScenarioReceipt.model_validate(receipt.model_dump())
    if not receipt.anchor.observed_at<=receipt.recorded_at<receipt.expires_at<=receipt.recorded_at+timedelta(hours=24):
        raise ValueError("JOINT_RECEIPT_CHRONOLOGY_OR_EXPIRY_INVALID")
    return joint_scenarios(receipt.anchor,receipt.assumptions,evaluated_at=receipt.recorded_at)


def persist_joint_receipt(folder: Path,receipt: JointScenarioReceipt) -> tuple[str,dict]:
    receipt=JointScenarioReceipt.model_validate(receipt.model_dump())
    computed=rederive(receipt)
    raw=_bytes(receipt)
    if len(raw)>MAX_SCENARIO_BYTES:
        raise ValueError("JOINT_SCENARIO_SIZE_LIMIT")
    digest=hashlib.sha256(raw).hexdigest()
    folder.mkdir(parents=True,exist_ok=True)
    base=folder.resolve(strict=True)
    path=base/(digest+".json")
    if not path.resolve().is_relative_to(base):
        raise ValueError("JOINT_SCENARIO_PATH_ESCAPE")
    if not path.exists():
        for count,_ in enumerate(base.iterdir(),start=1):
            if count>=MAX_SCENARIO_RECEIPTS:
                raise ValueError("JOINT_SCENARIO_COUNT_LIMIT")
        fd,temp=tempfile.mkstemp(prefix=".joint-",dir=base)
        try:
            with os.fdopen(fd,"wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp,path)
            except FileExistsError:
                pass
        finally:
            os.unlink(temp)
    if _read(path,MAX_SCENARIO_BYTES)!=raw:
        raise ValueError("JOINT_SCENARIO_PERSIST_MISMATCH")
    return digest,computed


def load_joint_receipt(folder: Path,anchor: PairPriceAnchor,*,now: datetime) -> dict:
    anchor=PairPriceAnchor.model_validate(anchor.model_dump())
    if now.utcoffset() is None or anchor.observed_at>now:
        raise ValueError("JOINT_RECEIPT_READ_TIME_INVALID")
    if not folder.is_dir():
        return {"status":"UNAVAILABLE","error_code":"NO_SCENARIO_FOR_EXACT_PAIR"}
    base=folder.resolve(strict=True)
    rows=[]
    for count,path in enumerate(base.iterdir(),start=1):
        if count>MAX_SCENARIO_RECEIPTS:
            raise ValueError("JOINT_SCENARIO_COUNT_LIMIT")
        if not re.fullmatch(r"[a-f0-9]{64}\.json",path.name):
            continue
        if not path.resolve(strict=True).is_relative_to(base):
            raise ValueError("JOINT_SCENARIO_PATH_ESCAPE")
        raw=_read(path,MAX_SCENARIO_BYTES)
        if hashlib.sha256(raw).hexdigest()!=path.stem:
            raise ValueError("JOINT_SCENARIO_HASH_MISMATCH")
        receipt=JointScenarioReceipt.model_validate_json(raw)
        if (_bytes(receipt)!=raw or receipt.anchor!=anchor or receipt.recorded_at>now
                or not receipt.anchor.observed_at<=receipt.recorded_at<receipt.expires_at<=receipt.recorded_at+timedelta(hours=24)):
            raise ValueError("JOINT_SCENARIO_SCOPE_OR_TIME_MISMATCH")
        rows.append((receipt.recorded_at,path.stem,receipt))
    if not rows:
        return {"status":"UNAVAILABLE","error_code":"NO_SCENARIO_FOR_EXACT_PAIR"}
    _,digest,receipt=max(rows,key=lambda item:(item[0],item[1]))
    metadata={"scenario_receipt_sha256":digest,"scenario_receipt_rehashed":True,
        "normalized_pair_sha256":anchor.normalized_pair_sha256,
        "recorded_at":receipt.recorded_at.isoformat(),"expires_at":receipt.expires_at.isoformat(),
        "decision_authority":False,"research_only":True,"execution_allowed":False}
    if now>=receipt.expires_at:
        return metadata | {"status":"UNAVAILABLE","error_code":"JOINT_SCENARIO_EXPIRED"}
    return rederive(receipt) | metadata
