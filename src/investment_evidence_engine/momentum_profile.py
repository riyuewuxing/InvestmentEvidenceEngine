"""Pure arithmetic for the existing fixed price-only momentum diagnostic.

No provider calls, historical vintage assertions, or execution authority.
"""
from __future__ import annotations

import math
from datetime import date

from .market_calendar import SCHEDULE_VERSION

WINDOW = 20
STRESS_BPS = (10, 20, 30)


def momentum_metrics(gross: list[float], targets: list[int], bps: int) -> dict:
    """One fresh-cash segment, trade at interval start, liquidate at terminal open."""
    if (type(bps) is not int or not 0 <= bps < 10000 or not gross or len(gross) != len(targets)
            or any(type(v) not in {int, float} or not math.isfinite(v) or v <= 0 for v in gross)
            or any(type(v) is not int or v not in (0, 1) for v in targets)):
        raise ValueError("RETROSPECTIVE_INVALID_METRICS_INPUT")
    wealth = 1.0
    peak = 1.0
    drawdown = 0.0
    turnover = 0
    old = 0
    c = bps / 10000
    for ratio, target in zip(gross, targets, strict=True):
        change = abs(target - old)
        turnover += change
        wealth *= 1 - c * change
        drawdown = max(drawdown, 1 - wealth / peak)
        wealth *= 1 + target * (ratio - 1)
        peak = max(peak, wealth)
        drawdown = max(drawdown, 1 - wealth / peak)
        old = target
    turnover += old
    wealth *= 1 - c * old
    drawdown = max(drawdown, 1 - wealth / peak)
    if not math.isfinite(wealth) or wealth <= 0:
        raise ValueError("RETROSPECTIVE_WEALTH_INVALID")
    net_change, max_drawdown = 100 * (wealth - 1), 100 * drawdown
    if not math.isfinite(net_change) or not math.isfinite(max_drawdown):
        raise ValueError("RETROSPECTIVE_NONFINITE_METRICS")
    return {"net_price_change_pct": net_change,
            "max_observed_open_drawdown_pct": max_drawdown,
            "unit_weight_turnover": turnover, "invested_intervals": sum(targets),
            "interval_count": len(targets)}


def momentum_profile(dates: tuple[date, ...], closes: list[float], opens: list[float]) -> dict:
    if (not isinstance(dates, tuple) or len(dates) != len(closes) or len(dates) != len(opens)
            or any(type(d) is not date for d in dates) or tuple(sorted(set(dates))) != dates
            or any(type(v) not in {int, float} or not math.isfinite(v) or v <= 0
                   for v in [*closes, *opens])):
        raise ValueError("RETROSPECTIVE_INVALID_INPUT")
    # Index t signal uses close[t-1] and close[t-1-WINDOW]. Label is
    # open[t+1]/open[t]. No label enters the signal or split selection.
    indices = list(range(WINDOW + 1, len(dates) - 1))
    if len(indices) < 220:
        raise ValueError("RETROSPECTIVE_INSUFFICIENT_INTERVALS")
    n = len(indices)
    a, b = n * 60 // 100, n * 80 // 100
    segments = (("train_reference", indices[:a - 1]),
                ("validation_reference", indices[a + 1:b - 1]),
                ("test_reference", indices[b + 1:]))
    report = []
    for name, group in segments:
        if len(group) < 40:
            raise ValueError("RETROSPECTIVE_SPLIT_TOO_SMALL")
        ratios = [opens[t + 1] / opens[t] for t in group]
        if not all(math.isfinite(x) and x > 0 for x in ratios):
            raise ValueError("RETROSPECTIVE_INVALID_RETURN")
        target = [int(closes[t - 1] > closes[t - 1 - WINDOW]) for t in group]
        report.append({"segment": name, "first_entry_open": dates[group[0]].isoformat(),
                       "terminal_open": dates[group[-1] + 1].isoformat(),
                       "intervals": len(group), "stress": [
                           {"one_way_bps": cost, "signal_rule": momentum_metrics(ratios, target, cost),
                            "constant_invested": momentum_metrics(ratios, [1] * len(group), cost),
                            "flat_cash_assumed_zero_interest": momentum_metrics(ratios, [0] * len(group), cost)}
                           for cost in STRESS_BPS]})
    return {"status": "RETROSPECTIVE_PRICE_DIAGNOSTIC_ONLY", "signal": "PRIOR_CLOSE_20_SESSION_RETURN_GT_ZERO",
            "return_interval": "NEXT_OPEN_TO_FOLLOWING_OPEN", "observations": len(dates),
            "eligible_intervals_before_split": n, "purged_or_embargoed_intervals": 4,
            "split_percent": [60, 20, 20], "purge": 1, "embargo": 1,
            "model_selection_performed": False, "test_segment_evaluations": 1,
            "cost_source": "GENERIC_ASSUMPTION_NOT_ACTUAL_ACCOUNT",
            "calendar_reference": SCHEDULE_VERSION, "schedule_dates_match": True,
            "calendar_independently_verified": False, "corporate_actions_verified": False,
            "historical_vintage_verified": False, "pit_safe": False,
            "actual_trade_feasibility_verified": False, "total_return": False,
            "forecast_validated": False, "research_only": True,
            "execution_allowed": False, "decision_authority": False,
            "segments": report}

