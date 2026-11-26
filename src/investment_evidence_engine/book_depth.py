"""Two-source same-timestamp displayed depth; strictly a snapshot sensitivity.

The undocumented vendor mappings are treated as an empirical convention, not
exchange-authoritative sizes. Both complete 5-level observations must agree
after the explicitly declared Tencent 100-unit-lot and Sina unit conversion.
No quote queue, latency, replenishment, auction, price limit or actual fill is
verified. A stock snapshot roundtrip is not a same-day trading recommendation.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from .historical_capture import PublicSecurity
from .quote_reference import _number, _text, parse_quote, quote_reference


def _depth(raw: bytes, subject: PublicSecurity, provider: str) -> tuple[tuple,tuple]:
    identity=subject.prefixed
    if provider=="tencent":
        parts=_text(raw,identity,"v_").split("~")
        bids=[(parts[i],parts[i+1]) for i in range(9,19,2)]
        asks=[(parts[i],parts[i+1]) for i in range(19,29,2)]
        lot_size=100
    elif provider=="sina":
        parts=_text(raw,identity,"var hq_str_").split(",")
        bids=[(parts[i+1],parts[i]) for i in range(10,20,2)]
        asks=[(parts[i+1],parts[i]) for i in range(20,30,2)]
        lot_size=1
    else:
        raise ValueError("DEPTH_PROVIDER_UNKNOWN")
    tick=Decimal("0.01" if subject.asset_type=="STOCK" else "0.001")
    def side(raw_levels, *, bid):
        levels=[]
        ended=False
        for price,size in raw_levels:
            p=Decimal(str(_number(price)))
            if not re.fullmatch(r"[0-9]+",size):
                raise ValueError("DEPTH_SIZE_SCHEMA_INVALID")
            units=int(size)*lot_size
            if p==0 and units==0:
                ended=True
                continue
            if ended or p<=0 or p%tick!=0 or not 0<units<=10000000000:
                raise ValueError("DEPTH_LEVEL_SCHEMA_INVALID")
            if levels and (p>=levels[-1][0] if bid else p<=levels[-1][0]):
                raise ValueError("DEPTH_ORDER_INVALID")
            levels.append((p,units))
        if not levels:
            raise ValueError("DEPTH_EMPTY_SIDE")
        return tuple(levels)
    return side(bids,bid=True),side(asks,bid=False)


def compare_displayed_depth(subject: PublicSecurity, tencent_raw: bytes, tencent_observed_at: datetime,
                            sina_raw: bytes, sina_observed_at: datetime,*,now: datetime) -> dict:
    a=parse_quote(tencent_raw,subject,"tencent",tencent_observed_at)
    b=parse_quote(sina_raw,subject,"sina",sina_observed_at)
    base={"subject_id":subject.symbol,"provider_at":a.provider_at.isoformat(),
          "size_mapping":"TENCENT_LOTS_X100_VS_SINA_UNITS_EMPIRICAL",
          "exchange_authoritative_depth_verified":False,"actual_fill_verified":False,
          "impact_cost_estimated":False,"decision_authority":False,"research_only":True,"execution_allowed":False}
    if any(quote_reference(q,now=now)["status"]!="OBSERVED_TOP_OF_BOOK_ONLY" for q in (a,b)):
        return base | {"status":"UNAVAILABLE","error_code":"DEPTH_QUOTE_NOT_CURRENT"}
    if a.provider_at!=b.provider_at:
        return base | {"status":"UNAVAILABLE","error_code":"DEPTH_TIMESTAMP_MISMATCH"}
    try:
        left,right=_depth(tencent_raw,subject,"tencent"),_depth(sina_raw,subject,"sina")
    except (ValueError,IndexError,ArithmeticError) as exc:
        return base | {"status":"UNAVAILABLE","error_code":str(exc) if str(exc).startswith("DEPTH_") else "DEPTH_SCHEMA_INVALID"}
    if left!=right:
        return base | {"status":"UNAVAILABLE","error_code":"DEPTH_PRICE_OR_SIZE_CONFLICT"}
    def render(levels):
        return [{"price_cny":float(price),"displayed_units":units} for price,units in levels]
    return base | {"status":"MATCHED_DISPLAYED_DEPTH_ONLY","bids":render(left[0]),"asks":render(left[1]),
                   "bid_displayed_units":sum(x[1] for x in left[0]),"ask_displayed_units":sum(x[1] for x in left[1])}


def depth_walk_scenario(subject: PublicSecurity,tencent_raw: bytes,tencent_observed_at: datetime,
                        sina_raw: bytes,sina_observed_at: datetime,*,now: datetime,side: str,units: int) -> dict:
    if type(units) is not int or not 0<units<=100000000 or side not in {"BUY","SELL"}:
        raise ValueError("DEPTH_SCENARIO_SIZE_OR_SIDE_INVALID")
    result=compare_displayed_depth(subject,tencent_raw,tencent_observed_at,sina_raw,sina_observed_at,now=now)
    if result["status"]!="MATCHED_DISPLAYED_DEPTH_ONLY":
        return result | {"requested_units":units,"side":side}
    levels=result["asks"] if side=="BUY" else result["bids"]
    remain=units
    cash=Decimal(0)
    for level in levels:
        filled=min(remain,level["displayed_units"])
        cash+=Decimal(str(level["price_cny"]))*filled
        remain-=filled
        if remain==0:
            break
    common={"subject_id":subject.symbol,"provider_at":result["provider_at"],"requested_units":units,
            "side":side,"displayed_book_only":True,"actual_fill_verified":False,
            "impact_cost_estimated":False,"formal_liquidity_cost_estimated":False,
            "execution_allowed":False,"decision_authority":False,"research_only":True}
    if remain:
        return common | {"status":"INSUFFICIENT_DISPLAYED_DEPTH","uncovered_units":remain}
    top=Decimal(str(levels[0]["price_cny"]))
    avg=cash/units
    adverse=(avg/top-1) if side=="BUY" else (1-avg/top)
    return common | {"status":"CONDITIONAL_STATIC_BOOK_WALK_ONLY","conditional_vwap_cny":float(avg),
                     "conditional_notional_cny":float(cash),"adverse_bps_from_best_quote":float(adverse*10000)}
