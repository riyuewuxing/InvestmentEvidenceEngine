"""Replay retained public event metadata, not historical first availability."""
from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from .evidence_time_guard import event_cutoff_status, parse_event_stamp

SH = ZoneInfo("Asia/Shanghai")
NY = ZoneInfo("America/New_York")
EXPECTED = {
    "2025-09-18": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20250917a.htm",
    "2025-12-11": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20251210a.htm",
}


def _clock(value: str) -> datetime:
    parsed, date_only = parse_event_stamp(value)
    if parsed is None or date_only or parsed.utcoffset() is None:
        raise ValueError("EVENT_CLOCK_UNKNOWN")
    return parsed


def _digest(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("EVENT_DIGEST")
    return value


def _unique(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("EVENT_DUPLICATE_KEY")
        out[k] = v
    return out


def _nonfinite(_value):
    raise ValueError("EVENT_NONFINITE")


def parse_public_event_observation(raw: bytes, *, now: datetime) -> tuple[dict, ...]:
    if now.utcoffset() is None or len(raw) > 32768:
        raise ValueError("EVENT_OBSERVATION_BOUNDARY")
    wrapper = json.loads(raw, object_pairs_hook=_unique, parse_constant=_nonfinite)
    if (wrapper["schema"] != "PUBLIC_FED_RETROSPECTIVE_CLOCK_OBSERVATION_V1"
            or wrapper["repo"] != "riyuewuxing/InvestmentEvidenceEngine"
            or any(wrapper[k] is not False for k in ("formal_admission", "decision_authority", "execution_allowed"))
            or not re.fullmatch(r"[0-9a-f]{40}", wrapper["executor_commit"])
            or any(type(wrapper[k]) is not int or wrapper[k] <= 0 for k in ("run_id", "job_id"))):
        raise ValueError("EVENT_WRAPPER_SCOPE")
    sources = {}
    diagnostics = {}
    if len(wrapper["log_lines"]) != 4:
        raise ValueError("EVENT_LOG_COUNT")
    for line in wrapper["log_lines"]:
        log_at, marker, payload = line.split(" ", 2)
        log_clock = _clock(log_at)
        if log_clock > now:
            raise ValueError("EVENT_LOG_FUTURE")
        row = json.loads(payload, object_pairs_hook=_unique, parse_constant=_nonfinite)
        url = row["source_url"]
        if url not in EXPECTED.values() or row["decision_authority"] is not False:
            raise ValueError("EVENT_SOURCE_SCOPE")
        _digest(row["source_sha256"])
        if marker == "PUBLIC_FED_CLOCK_RECEIPT":
            if url in sources or any(row[k] is not False for k in (
                    "actual_historical_availability_verified", "historical_retrieval_verified", "raw_body_retained")):
                raise ValueError("EVENT_SOURCE_AUTHORITY")
            published = _clock(row["declared_release_at"])
            retrieved = _clock(row["retrieved_at"])
            if not published <= retrieved <= log_clock or published.astimezone(NY).time() != time(14):
                raise ValueError("EVENT_SOURCE_CLOCK")
            if _clock(row["shanghai_release_at"]) != published or published.astimezone(SH).time() >= time(8, 30):
                raise ValueError("EVENT_SOURCE_LOCAL_CLOCK")
            sources[url] = row
        elif marker == "PUBLIC_EVENT_DIAGNOSTIC":
            if url in diagnostics or row["status"] != "RETROSPECTIVE_EVENT_PRICE_DIAGNOSTIC_ONLY":
                raise ValueError("EVENT_DIAGNOSTIC_SCOPE")
            if any(row[k] is not False for k in (
                    "causal_effect_estimated", "future_return_estimated", "historical_blind_replay",
                    "historical_retrieval_verified", "historical_vintage_verified", "open_prices_available",
                    "statistical_significance_estimated", "execution_allowed", "corporate_action_coverage_verified")):
                raise ValueError("EVENT_DIAGNOSTIC_AUTHORITY")
            if row["research_only"] is not True or row["price_basis"] != "RAW_CLOSE_WITHOUT_DISTRIBUTIONS":
                raise ValueError("EVENT_PRICE_SCOPE")
            if _clock(row["calendar_observed_at"]) > log_clock:
                raise ValueError("EVENT_CALENDAR_CLOCK")
            diagnostics[url] = row
        else:
            raise ValueError("EVENT_MARKER")
    out = []
    for day, url in EXPECTED.items():
        s, d = sources[url], diagnostics[url]
        p, r = _clock(s["declared_release_at"]), _clock(s["retrieved_at"])
        if (d["source_sha256"] != s["source_sha256"] or _clock(d["declared_release_at"]) != p
                or p.astimezone(SH).date().isoformat() != day or d["event_session"] != day
                or d["candidate_subject_id"] != "600519" or d["benchmark_subject_id"] != "510050"
                or d["before_auction_reference"] is not True):
            raise ValueError("EVENT_BINDING")
        _digest(d["normalized_receipt_sha256"])
        windows = d["windows"]
        if [x["sessions"] for x in windows] != [1, 3, 5] or windows[0]["end_session"] != day:
            raise ValueError("EVENT_HORIZONS")
        values = []
        for w in windows:
            a, b, car = (w[k] for k in ("candidate_close_return_pct", "benchmark_close_return_pct",
                                       "market_model_arithmetic_car_pct"))
            if any(type(x) not in (int, float) or not math.isfinite(x) for x in (a, b, car)):
                raise ValueError("EVENT_METRIC")
            values.append({"sessions": w["sessions"], "candidate_close_return_pct": a,
                           "benchmark_close_return_pct": b, "car_pct": car,
                           "end_session": w["end_session"],
                           "listed_benchmark_ex_date_in_window": w["listed_benchmark_ex_date_in_window"]})
        local = p.astimezone(SH)
        before = local.replace(hour=8, minute=30)
        auction = local.replace(hour=9, minute=26)
        out.append({
            "event_session": day, "source_url": url, "source_sha256": s["source_sha256"],
            "declared_release_at": p.isoformat(), "shanghai_release_at": local.isoformat(),
            "retrieved_at": r.astimezone(UTC).isoformat(),
            "declared_before_premarket": p < before,
            "actual_receipt_at_premarket": event_cutoff_status(p.isoformat(), r.isoformat(), before.isoformat()),
            "actual_receipt_at_auction": event_cutoff_status(p.isoformat(), r.isoformat(), auction.isoformat()),
            "actual_receipt_at_retrieval": event_cutoff_status(p.isoformat(), r.isoformat(), r.isoformat()),
            "observed_price_sign": "POSITIVE" if values[0]["car_pct"] > 0 else "NEGATIVE" if values[0]["car_pct"] < 0 else "ZERO",
            "windows": values, "historical_blind_replay": False, "historical_first_availability_verified": False,
            "causal_effect_estimated": False, "formal_admission": False, "decision_authority": False,
            "execution_allowed": False, "source_run": wrapper["run_id"],
        })
    return tuple(out)
