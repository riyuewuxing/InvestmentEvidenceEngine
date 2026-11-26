"""Date-uncertain issuer event sensitivity, not a trade or event-time certification."""
from __future__ import annotations

from datetime import date

from .historical_capture import PublicSecurity, summarize_observed_pair
from .historical_reference import HistoricalCloseSeries, event_price_window_reference
from .market_calendar import SCHEDULE_VERSION, scheduled_days

FIRST = date(2026, 8, 24)
LAST = date(2026, 11, 6)
DECLARED = date(2026, 10, 29)
ISSUER = PublicSecurity(symbol="000035", asset_type="STOCK")
BENCHMARK = PublicSecurity(symbol="510300", asset_type="ETF")
DOCUMENT_SHA = "dedeb15450b3005cb8f509cf1d3409347a76170ae5c7e9c5f21de04645ea3639"


def event_sensitivity(series: tuple[HistoricalCloseSeries, ...]) -> dict:
    """Both plausible event-day conventions, fixed before prices are inspected.

    Do not choose the more favorable return or infer event-day ordering from
    an announcement platform midnight timestamp. No claim of actual publication
    inside the modeled window; date sensitivity is retrospective.
    """
    report = {"status": "BLOCK", "decision_authority": False, "execution_allowed": False,
              "research_only": True, "historical_vintage_verified": False,
              "corporate_action_coverage_verified": False, "pit_safe": False,
              "first_public_availability_verified": False,
              "declared_report_date": DECLARED.isoformat(), "document_sha256": DOCUMENT_SHA,
              "price_basis": "RAW_CLOSE_WITHOUT_DISTRIBUTIONS", "calendar_version": SCHEDULE_VERSION}
    pair = summarize_observed_pair(ISSUER, BENCHMARK, series, FIRST, LAST)
    report["pair"] = pair
    if pair["status"] != "OBSERVED_REFERENCE_ONLY" or pair["crosscheck"] != "MATCH":
        return report | {"blocker": "TWO_SOURCE_PER_ASSET_REQUIRED"}
    sessions = tuple(row.day for row in scheduled_days(FIRST, LAST) if row.is_trading_day)
    if DECLARED not in sessions:
        raise ValueError("DECLARED_DATE_NOT_SCHEDULED")
    next_session = sessions[sessions.index(DECLARED)+1]
    # Compare every qualifying source-pair combination rather than hide a
    # within-tolerance price difference behind a single arbitrarily chosen pair.
    variants = []
    for left in (s for s in series if s.subject_id == ISSUER.symbol):
        for right in (s for s in series if s.subject_id == BENCHMARK.symbol):
            for day in (DECLARED, next_session):
                result = event_price_window_reference(left, right, sessions=sessions, event_session=day)
                variants.append({"candidate_provider": left.source_label,
                                 "benchmark_provider": right.source_label, "event": result})
    ranges = []
    for horizon in (1, 3, 5):
        rows = [window for variant in variants for window in variant["event"]["windows"]
                if window["sessions"] == horizon]
        excess = [row["close_return_difference_pp"] for row in rows]
        car = [row["market_model_arithmetic_car_pct"] for row in rows]
        ranges.append({"sessions": horizon, "candidate_minus_etf_pp_min": min(excess),
                       "candidate_minus_etf_pp_max": max(excess),
                       "market_model_car_pct_min": min(car), "market_model_car_pct_max": max(car)})
    return report | {"status": "WARN", "event_day_conventions": [DECLARED.isoformat(), next_session.isoformat()],
                     "convention_selected": False, "variants": variants,
                     "sensitivity_ranges": ranges, "causal_effect_estimated": False,
                     "forecast_validated": False, "same_original_upstream_independence_unverified": True}
