"""Fixed momentum research execution, distinct from formal PIT admission.

Consume the actual sealed market artifact, not a caller-supplied assertion of
historical vintage. A successful arithmetic diagnostic never upgrades RESEARCH
to WARN/PASS while the actual formal source prerequisites are missing.
"""
from __future__ import annotations

import hashlib
import math
from datetime import date, timedelta

import pandas as pd

from .contracts import ArtifactRef, ExecutionOperation, OperationResult, canonical_sha256
from .historical_capture import PublicSecurity
from .market_calendar import SCHEDULES, scheduled_days
from .retrospective_control import retrospective_momentum
from .snapshot_integrity import strict_json_loads
from .transport_integrity import read_verified_artifact
from .workers import WorkerContext, _artifact, _write_json

PROFILE = "SINGLE_ASSET_MOMENTUM_V1"
FACTOR = {"field": "close", "transform": "ROLLING_RETURN", "window": 20, "operator": "GT_ZERO"}
SPLIT = {"method": "CHRONOLOGICAL", "train_pct": 60, "validation_pct": 20, "test_pct": 20,
         "purge": 1, "embargo": 1, "selection": "FIXED_PREDECLARED_NO_TUNING",
         "test_policy": "TEST_FINAL_ONCE"}
COST = {"base_bps": 10.0, "stress_multipliers": [1, 2, 3],
        "source": "RESEARCH_ASSUMPTION_NOT_BROKER_VERIFIED"}
FORMAL_BLOCKER = "RESEARCH_POINT_IN_TIME_SOURCE_VINTAGE_AND_PROFILE_NOT_ADMITTED"


def check_profile(params: dict) -> None:
    expected = {"profile": PROFILE, "factor": FACTOR, "split": SPLIT, "cost": COST,
                "semantics": "RESEARCH_ONLY_NOT_ADVICE", "market": "CN_A", "asset_type": "STOCK"}
    if any(canonical_sha256(params.get(k)) != canonical_sha256(v) for k, v in expected.items()):
        raise ValueError("RESEARCH_FIXED_PROFILE_CONTRACT_MISMATCH")
    if set(params) != set(expected) | {"as_of", "depends_on_operation_ids", "input_artifact_ids"}:
        raise ValueError("RESEARCH_PROFILE_UNEXPECTED_PARAMETERS")


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
    diagnostic = retrospective_momentum(pd.DataFrame(bars), first, last)
    return {"profile": PROFILE, "symbol": symbol, "as_of": as_of,
            "input_bars_sha256": canonical_sha256(bars),
            "input_market_sha256": hashlib.sha256(raw).hexdigest(),
            "input_market_size_bytes": len(raw), "raw_price_diagnostic": diagnostic,
            "formal_profile_admitted": False, "historical_source_vintage_verified": False,
            "actual_costs_verified": False, "source_independence_verified": False,
            "research_only": True, "pit_safe": False,
            "decision_authority": False, "execution_allowed": False}


def run_research(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    params = operation.parameters
    ids = params.get("input_artifact_ids")
    ref = (context.input_artifacts.get(ids[0]) if isinstance(ids, list) and len(ids) == 1
           and isinstance(ids[0], str) else None)
    cutoff = params.get("as_of")
    attachment_scope = bool(ref is not None and isinstance(cutoff, str)
                            and ref.as_of == cutoff == context.request_as_of)
    deps = params.get("depends_on_operation_ids")
    dep = deps[0] if isinstance(deps, list) and len(deps) == 1 and isinstance(deps[0], str) else None
    provenance = context.completed_operations.get(dep, {}) if dep else {}
    payload = context.payloads.get(dep, {}) if dep else {}
    frame = context.frames.get(dep) if dep else None
    scoped_market = bool(attachment_scope and provenance.get("kind") == "MARKET_DATA"
                         and provenance.get("status") in {"PASS", "WARN"}
                         and provenance.get("as_of") == cutoff
                         and isinstance(payload, dict) and payload.get("as_of") == cutoff
                         and payload.get("symbol") == ref.selector.value
                         and frame is not None and not frame.empty)
    readiness = {
        "candidate_attachment": "CONTEXT_SCOPE_MATCH_TRANSPORT_ONLY" if attachment_scope else "UNVERIFIED",
        "market_input": "OBSERVED_SCOPE_MATCH_ONLY" if scoped_market else "UNVERIFIED",
        "profile_requested": params.get("profile") == PROFILE,
        "historical_source_vintage": "NOT_ADMITTED",
        "historical_listing_and_corporate_actions": "NOT_ADMITTED",
        "historical_execution_and_costs": "NOT_ADMITTED",
        "formal_profile": "NOT_ADMITTED",
        "private_source_graph": "NOT_VERIFIED_BY_PUBLIC_ENGINE",
        "research_admitted": False, "pit_safe": False,
        "decision_authority": False, "execution_allowed": False,
        "arithmetic_profile": "NOT_RUN",
    }
    artifacts = []
    if scoped_market and readiness["profile_requested"]:
        try:
            check_profile(params)
            refs = provenance.get("artifact_refs")
            if not isinstance(refs, list) or len(refs) != 1:
                raise ValueError("RESEARCH_MARKET_ARTIFACT_REQUIRED")
            market_ref = ArtifactRef.model_validate(refs[0])
            if market_ref.path != dep + ".json":
                raise ValueError("RESEARCH_MARKET_ARTIFACT_PATH")
            raw = read_verified_artifact(context.output_dir, market_ref.path,
                                         market_ref.sha256, market_ref.size_bytes)
            if strict_json_loads(raw) != payload:
                raise ValueError("RESEARCH_MARKET_ARTIFACT_CONTEXT_MISMATCH")
            # Read the retained scan attachment again; the result is bound to
            # exact candidate bytes, not to the unverified declared source graph.
            from .input_binding import observe_scan_input

            receipt, _ = observe_scan_input(context.output_dir, ref)
            report = evaluate_market_profile(raw, symbol=ref.selector.value, as_of=cutoff)
            report |= {"status": "BLOCK", "formal_blocker": FORMAL_BLOCKER,
                       "candidate_attachment_sha256": receipt.observed_sha256,
                       "candidate_record_sha256": ref.selector.record_sha256,
                       "source_operation_id": dep, "source_graph_verified": False,
                       "historical_selection_verified": False}
            path = context.output_dir / f"{operation.operation_id}.json"
            _write_json(path, report)
            artifacts = [_artifact(path, media_type="application/json")]
            readiness["arithmetic_profile"] = "EXECUTED_RETROSPECTIVE_ONLY"
            readiness["market_input"] = "EXACT_ARTIFACT_BYTES_AND_OBSERVED_SCOPE_MATCH"
        except (ValueError, TypeError, KeyError, OSError, RuntimeError, OverflowError) as exc:
            reason = str(exc)
            readiness["arithmetic_profile"] = "BLOCK"
            readiness["arithmetic_blocker"] = reason if reason.startswith("RESEARCH_") else type(exc).__name__
    return OperationResult(operation_id=operation.operation_id, status="BLOCK", exit_code=2,
                           errors=[FORMAL_BLOCKER], artifacts=artifacts,
                           metrics={"research_readiness": readiness})
