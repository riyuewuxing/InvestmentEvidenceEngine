"""Portable exact-byte validation and arithmetic for a price-only diagnostic.

No provider calls, private graph, historical PIT or admission authority.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta

from .historical_capture import PublicSecurity
from .market_calendar import SCHEDULES, scheduled_days
from .momentum_profile import momentum_profile
from .snapshot_integrity import strict_json_loads

PROFILE = "SINGLE_ASSET_MOMENTUM_V1"
FACTOR = {"field": "close", "transform": "ROLLING_RETURN", "window": 20, "operator": "GT_ZERO"}
SPLIT = {"method": "CHRONOLOGICAL", "train_pct": 60, "validation_pct": 20, "test_pct": 20,
         "purge": 1, "embargo": 1, "selection": "FIXED_PREDECLARED_NO_TUNING",
         "test_policy": "TEST_FINAL_ONCE"}
COST = {"base_bps": 10.0, "stress_multipliers": [1, 2, 3],
        "source": "RESEARCH_ASSUMPTION_NOT_BROKER_VERIFIED"}
FORMAL_BLOCKER = "RESEARCH_POINT_IN_TIME_SOURCE_VINTAGE_AND_PROFILE_NOT_ADMITTED"


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def check_profile(params: dict) -> None:
    expected = {"profile": PROFILE, "factor": FACTOR, "split": SPLIT, "cost": COST,
                "semantics": "RESEARCH_ONLY_NOT_ADVICE", "market": "CN_A", "asset_type": "STOCK"}
    if any(canonical_sha256(params.get(k)) != canonical_sha256(v) for k, v in expected.items()):
        raise ValueError("RESEARCH_FIXED_PROFILE_CONTRACT_MISMATCH")
    if set(params) != set(expected) | {"as_of", "depends_on_operation_ids", "input_artifact_ids"}:
        raise ValueError("RESEARCH_PROFILE_UNEXPECTED_PARAMETERS")


def check_market_request(params: dict, raw: bytes, *, symbol: str, as_of: str, input_id: str) -> None:
    """Bind the exact observed window to the upstream operation request."""
    if not isinstance(params, dict):
        raise ValueError("RESEARCH_MARKET_REQUEST_REQUIRED")
    expected = {"as_of": as_of, "subject_ids": [symbol], "input_artifact_ids": [input_id],
                "adjust": "", "history_end_offset_days": 1, "price_tolerance": 0.001}
    if (any(canonical_sha256(params.get(k)) != canonical_sha256(v) for k, v in expected.items())
            or type(params.get("history_days")) is not int or not 30 <= params["history_days"] <= 1100):
        raise ValueError("RESEARCH_MARKET_REQUEST_SCOPE")
    last = date.fromisoformat(as_of) - timedelta(days=1)
    first = last - timedelta(days=params["history_days"])
    data = strict_json_loads(raw)
    if not isinstance(data, dict) or (data.get("start"), data.get("end")) != (first.isoformat(), last.isoformat()):
        raise ValueError("RESEARCH_MARKET_REQUEST_WINDOW_MISMATCH")


def evaluate_market_profile(raw: bytes, *, symbol: str, as_of: str) -> dict:
    """Run the fixed arithmetic profile from exact observed serialized price rows.

    Calendar range is explicitly bounded to reviewed schedule years; no
    truncation, gap filling, qfq/hfq substitution, or as-of proxy allowed.
    """
    PublicSecurity(symbol=symbol, asset_type="STOCK").prefixed
    day = date.fromisoformat(as_of)
    if day.isoformat() != as_of:
        raise ValueError("RESEARCH_PROFILE_DATE_SCOPE")
    payload = strict_json_loads(raw)
    if (not isinstance(payload, dict)
            or (payload.get("symbol"), payload.get("as_of"), payload.get("adjust")) != (symbol, as_of, "")
            or type(payload.get("history_end_offset_days")) is not int
            or payload["history_end_offset_days"] != 1
            or payload.get("pit_safe") is not False
            or payload.get("historical_vintage_verified") is not False
            or payload.get("decision_authority") is not False):
        raise ValueError("RESEARCH_RAW_MARKET_SCOPE_REQUIRED")
    first, last = date.fromisoformat(payload["start"]), date.fromisoformat(payload["end"])
    if (first.isoformat(), last.isoformat()) != (payload["start"], payload["end"]):
        raise ValueError("RESEARCH_MARKET_DATE_SCHEMA")
    if (not first <= last <= day - timedelta(days=1)
            or not 0 < (last - first).days <= 1100
            or first.year not in SCHEDULES or last.year not in SCHEDULES):
        raise ValueError("RESEARCH_MARKET_WINDOW_UNSUPPORTED")
    # The market worker is asked for an exact offset of one calendar day.
    if last != day - timedelta(days=1):
        raise ValueError("RESEARCH_MARKET_END_MISMATCH")
    bars = payload.get("bars")
    cross = payload.get("crosscheck")
    if not isinstance(bars, list) or not 0 < len(bars) <= 756 or not isinstance(cross, dict):
        raise ValueError("RESEARCH_MARKET_RECORDS_REQUIRED")
    expected_days = tuple(r.day for r in scheduled_days(first, last) if r.is_trading_day)
    if not expected_days:
        raise ValueError("RESEARCH_MARKET_CALENDAR_EMPTY")
    if (cross.get("status") != "MATCH_OBSERVED_ROWS"
            or type(cross.get("overlap_rows")) is not int or cross["overlap_rows"] != len(bars)
            or type(cross.get("left_only_dates")) is not int or cross["left_only_dates"] != 0
            or type(cross.get("right_only_dates")) is not int or cross["right_only_dates"] != 0
            or cross.get("latest_common_date") != expected_days[-1].isoformat()
            or type(cross.get("tolerance")) not in {int, float} or cross["tolerance"] != 0.001
            or type(cross.get("max_relative_price_diff")) not in {int, float}
            or not math.isfinite(cross["max_relative_price_diff"])
            or not 0 <= cross["max_relative_price_diff"] <= 0.001):
        raise ValueError("RESEARCH_EXACT_WINDOW_CROSSCHECK_REQUIRED")
    providers = payload.get("providers")
    if not isinstance(providers, list) or not all(isinstance(p, dict) for p in providers):
        raise ValueError("RESEARCH_PROVIDER_RECEIPTS_REQUIRED")
    observed = [p for p in providers if p.get("status") == "OBSERVED"]
    if (len(observed) != 2 or len({p.get("upstream") for p in observed}) != 2
            or any(p.get("upstream") not in {"sina", "eastmoney", "baostock", "tencent"} for p in observed)
            or not any(p.get("upstream") == "tencent" and p.get("raw_body_parent_rehash") == "MATCH"
                       for p in observed)
            or any(type(p.get("rows")) is not int or p["rows"] != len(bars) for p in observed)):
        raise ValueError("RESEARCH_TWO_ROUTE_RAW_RECEIPTS_REQUIRED")
    required = {"date", "open", "high", "low", "close", "volume"}
    if not all(isinstance(row, dict) and required <= set(row) for row in bars):
        raise ValueError("RESEARCH_MARKET_ROW_SCHEMA")
    # Check identity labels if present; the production market envelope
    # otherwise carries identity. Avoid sorting a malformed input into validity.
    for row in bars:
        if any(row[k] != symbol for k in ("symbol", "code", "subject_id", "asset", "asset_id") if k in row):
            raise ValueError("RESEARCH_MARKET_ROW_IDENTITY")
        if any(type(row[k]) not in {int, float} or not math.isfinite(row[k])
               for k in required - {"date"}):
            raise ValueError("RESEARCH_MARKET_ROW_NUMERIC")
    dates = []
    for row in bars:
        value = row["date"]
        if not isinstance(value, str):
            raise ValueError("RESEARCH_MARKET_ROW_DATE")
        d = date.fromisoformat(value[:10])
        if value not in {d.isoformat(), d.isoformat() + "T00:00:00.000"}:
            raise ValueError("RESEARCH_MARKET_ROW_DATE")
        dates.append(d)
    if tuple(dates) != expected_days:
        raise ValueError("RESEARCH_MARKET_SESSION_COVERAGE")
    for row in bars:
        if (min(row["open"], row["high"], row["low"], row["close"]) <= 0
                or row["volume"] <= 0
                or row["high"] < max(row["open"], row["close"], row["low"])
                or row["low"] > min(row["open"], row["close"], row["high"])):
            raise ValueError("RESEARCH_MARKET_ROW_OHLCV")
    diagnostic = momentum_profile(tuple(dates), [float(row["close"]) for row in bars],
                                  [float(row["open"]) for row in bars])
    return {"profile": PROFILE, "symbol": symbol, "as_of": as_of,
            "input_bars_sha256": canonical_sha256(bars),
            "input_market_sha256": hashlib.sha256(raw).hexdigest(),
            "input_market_size_bytes": len(raw), "raw_price_diagnostic": diagnostic,
            "formal_profile_admitted": False, "historical_source_vintage_verified": False,
            "actual_costs_verified": False, "source_independence_verified": False,
            "research_only": True, "pit_safe": False,
            "decision_authority": False, "execution_allowed": False}


def verify_diagnostic(raw_market: bytes, raw_diagnostic: bytes, *,
                      symbol: str, as_of: str, candidate_sha256: str,
                      record_sha256: str, source_operation_id: str) -> dict:
    """Independently recalculate every diagnostic field; no declaration-only admission."""
    expected = evaluate_market_profile(raw_market, symbol=symbol, as_of=as_of)
    expected |= {"status": "BLOCK", "formal_blocker": FORMAL_BLOCKER,
                 "candidate_attachment_sha256": candidate_sha256,
                 "candidate_record_sha256": record_sha256,
                 "source_operation_id": source_operation_id, "source_graph_verified": False,
                 "historical_selection_verified": False}
    observed = strict_json_loads(raw_diagnostic)
    if canonical_sha256(observed) != canonical_sha256(expected):
        raise ValueError("RESEARCH_DIAGNOSTIC_RECOMPUTATION_MISMATCH")
    return expected
