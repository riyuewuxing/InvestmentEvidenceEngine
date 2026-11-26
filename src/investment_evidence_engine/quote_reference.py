"""Timestamped vendor top-of-book observations, not executable cost.

Strict response identity and exact provider clock are required. No stale
or out-of-session quote is called current. Prices only: depth size units
and queue execution are not asserted from undocumented wire fields.
Raw vendor bytes may be stored locally, never uploaded by the public smoke.
"""
from __future__ import annotations

import hashlib
import re
import urllib.request
from datetime import datetime, time
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat

from .historical_capture import SH, PublicSecurity
from .market_calendar import scheduled_days

MAX_BYTES = 64 * 1024
MAX_AGE_SECONDS = 90
MAX_CROSSCHECK_SKEW = 5
PROVIDERS = ("tencent","sina")


class QuoteObservation(BaseModel):
    model_config = ConfigDict(extra="forbid",frozen=True,strict=True)
    subject: PublicSecurity
    provider: Literal["tencent","sina"]
    provider_at: AwareDatetime
    observed_at: AwareDatetime
    bid: FiniteFloat = Field(gt=0,le=1e6)
    ask: FiniteFloat = Field(gt=0,le=1e6)
    last: FiniteFloat = Field(gt=0,le=1e6)
    raw_response_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def _text(raw: bytes, identity: str, prefix: str) -> str:
    if not raw or len(raw)>MAX_BYTES:
        raise ValueError("QUOTE_BODY_SIZE_INVALID")
    try:
        decoded=raw.decode("gb18030")
    except UnicodeError as exc:
        raise ValueError("QUOTE_BODY_ENCODING_INVALID") from exc
    # Match only a single requested variable, not an arbitrary ticker substring.
    match=re.fullmatch(r'\s*'+re.escape(prefix+identity)+r'="([^"\r\n]*)";?\s*',decoded)
    if match is None:
        raise ValueError("QUOTE_WIRE_IDENTITY_INVALID")
    return match.group(1)


def _number(value: str) -> float:
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?",value):
        raise ValueError("QUOTE_PRICE_SCHEMA_INVALID")
    return float(value)


def _timestamp(value: str, fmt: str) -> datetime:
    return datetime.strptime(value,fmt).replace(tzinfo=SH)


def parse_quote(raw: bytes, subject: PublicSecurity, provider: str, observed_at: datetime) -> QuoteObservation:
    if observed_at.utcoffset() is None:
        raise ValueError("QUOTE_OBSERVATION_TIME_INVALID")
    identity=subject.prefixed
    if provider=="tencent":
        fields=_text(raw,identity,"v_").split("~")
        if len(fields)<31 or fields[2]!=subject.symbol or not re.fullmatch(r"[0-9]{14}",fields[30]):
            raise ValueError("TENCENT_QUOTE_SCHEMA_INVALID")
        bid,ask,last=map(_number,(fields[9],fields[19],fields[3]))
        stamped=_timestamp(fields[30],"%Y%m%d%H%M%S")
    elif provider=="sina":
        fields=_text(raw,identity,"var hq_str_").split(",")
        if len(fields)<32:
            raise ValueError("SINA_QUOTE_SCHEMA_INVALID")
        bid,ask,last=map(_number,(fields[11],fields[21],fields[3]))
        stamped=_timestamp(fields[30]+" "+fields[31],"%Y-%m-%d %H:%M:%S")
    else:
        raise ValueError("QUOTE_PROVIDER_UNSUPPORTED")
    if bid>ask:
        raise ValueError("CROSSED_TOP_OF_BOOK")
    # Price increment only; not lot size or instrument trading eligibility.
    tick=Decimal("0.01" if subject.asset_type=="STOCK" else "0.001")
    if any(Decimal(str(value))%tick!=0 for value in (bid,ask,last)):
        raise ValueError("QUOTE_TICK_MISMATCH")
    if stamped>observed_at:
        raise ValueError("QUOTE_TIMESTAMP_IN_FUTURE")
    return QuoteObservation(subject=subject,provider=provider,provider_at=stamped,
        observed_at=observed_at,bid=bid,ask=ask,last=last,
        raw_response_sha256=hashlib.sha256(raw).hexdigest())


def _continuous(stamp: datetime) -> bool:
    local=stamp.astimezone(SH)
    current=local.time()
    return (scheduled_days(local.date(),local.date())[0].is_trading_day
            and (time(9,30)<=current<time(11,30) or time(13)<=current<time(14,57)))


def quote_reference(quote: QuoteObservation, *, now: datetime) -> dict:
    quote=QuoteObservation.model_validate(quote.model_dump())
    if now.utcoffset() is None or not quote.provider_at<=quote.observed_at<=now:
        raise ValueError("QUOTE_CHRONOLOGY_INVALID")
    age=(now-quote.provider_at).total_seconds()
    result={"subject_id":quote.subject.symbol,"asset_type":quote.subject.asset_type,
        "provider":quote.provider,"provider_at":quote.provider_at.isoformat(),
        "observed_at":quote.observed_at.isoformat(),"age_seconds":age,
        "raw_response_sha256":quote.raw_response_sha256,
        "actual_fill_verified":False,"market_depth_verified":False,"impact_cost_estimated":False,
        "formal_liquidity_cost_estimated":False,"decision_authority":False,
        "research_only":True,"execution_allowed":False}
    if age>MAX_AGE_SECONDS:
        return result | {"status":"UNAVAILABLE","error_code":"QUOTE_STALE"}
    if not _continuous(quote.provider_at) or not _continuous(now):
        return result | {"status":"UNAVAILABLE","error_code":"OUTSIDE_CONTINUOUS_AUCTION"}
    mid=(Decimal(str(quote.bid))+Decimal(str(quote.ask)))/2
    spread=Decimal(str(quote.ask))-Decimal(str(quote.bid))
    return result | {"status":"OBSERVED_TOP_OF_BOOK_ONLY","bid_cny":quote.bid,"ask_cny":quote.ask,
        "last_cny":quote.last,"mid_cny":float(mid),"full_quoted_spread_bps_of_mid":float(spread/mid*10000),
        "instantaneous_hypothetical_roundtrip_loss_bps_of_ask":float(spread/Decimal(str(quote.ask))*10000),
        "price_source_mapping":"UNDOCUMENTED_VENDOR_WIRE_LAYOUT_EMPIRICALLY_CHECKED",
        "scope_note":"ONE_DISPLAYED_PRICE_SNAPSHOT_NO_SIZE_OR_QUEUE_OR_FUTURE_EXIT"}


def crosscheck_quotes(left: QuoteObservation,right: QuoteObservation,*,now: datetime) -> dict:
    a,b=quote_reference(left,now=now),quote_reference(right,now=now)
    if left.subject!=right.subject or left.provider==right.provider:
        raise ValueError("QUOTE_CROSSCHECK_IDENTITY_INVALID")
    skew=abs((left.provider_at-right.provider_at).total_seconds())
    if a["status"]!="OBSERVED_TOP_OF_BOOK_ONLY" or b["status"]!="OBSERVED_TOP_OF_BOOK_ONLY":
        status="UNAVAILABLE"
    elif skew>MAX_CROSSCHECK_SKEW:
        status="ASYNCHRONOUS_NOT_COMPARABLE"
    elif (left.bid,left.ask)!=(right.bid,right.ask):
        status="DIFFERENT_DISPLAYED_PRICES"
    else:
        status="DISPLAYED_BID_ASK_MATCH"
    return {"status":status,"timestamp_skew_seconds":skew,"independent_upstream_verified":False,
        "decision_authority":False}


def acquire_quote(subject: PublicSecurity,provider: str) -> tuple[bytes,QuoteObservation]:
    identity=subject.prefixed
    if provider=="tencent":
        url="https://qt.gtimg.cn/q="+identity
        headers={"User-Agent":"Mozilla/5.0","Referer":"https://gu.qq.com/"}
    elif provider=="sina":
        url="https://hq.sinajs.cn/list="+identity
        headers={"User-Agent":"Mozilla/5.0","Referer":"https://finance.sina.com.cn/"}
    else:
        raise ValueError("QUOTE_PROVIDER_UNSUPPORTED")
    request=urllib.request.Request(url,headers=headers)
    with urllib.request.urlopen(request,timeout=8) as response:
        raw=response.read(MAX_BYTES+1)
    return raw,parse_quote(raw,subject,provider,datetime.now(SH))
