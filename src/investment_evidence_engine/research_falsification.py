"""Predeclared, price-only falsification of a fixed descriptive momentum rule.

This is not statistical validation, historical PIT, total return or trade advice.
It does not alter the sealed prospective experiment or select a new strategy.
"""
from __future__ import annotations

import math
from decimal import Decimal, localcontext

from .evidence_time_guard import market_daily_label

COST_TIERS = (10, 20, 30)
CONTROL_SYMBOLS = ("600036", "600900")
CONTROL_START = "2025-01-02"
CONTROL_END = "2026-11-25"
CONTROL_AS_OF = "2026-11-26"
CRITERION = "TEST_SIGNAL_STRICTLY_BEATS_BOTH_MATCHED_BASELINES_AT_EVERY_PREDECLARED_COST"


def assess_test_segment(diagnostic: dict) -> dict:
    """A single failed comparison refutes the stated conditional dominance claim."""
    if (not isinstance(diagnostic, dict)
            or diagnostic.get("status") != "RETROSPECTIVE_PRICE_DIAGNOSTIC_ONLY"
            or any(diagnostic.get(flag) is not False for flag in
                   ("pit_safe", "decision_authority", "execution_allowed", "forecast_validated",
                    "total_return", "historical_vintage_verified", "model_selection_performed"))
            or type(diagnostic.get("test_segment_evaluations")) is not int
            or diagnostic["test_segment_evaluations"] != 1):
        raise ValueError("FALSIFICATION_DIAGNOSTIC_SCOPE")
    segments = diagnostic.get("segments")
    if (not isinstance(segments, list) or not all(isinstance(s, dict) for s in segments)
            or [s.get("segment") for s in segments] !=
            ["train_reference", "validation_reference", "test_reference"]):
        raise ValueError("FALSIFICATION_SPLIT_SCOPE")
    test = segments[-1]
    n = test.get("intervals")
    rows = test.get("stress")
    if (type(n) is not int or n < 40 or not isinstance(rows, list)
            or not all(isinstance(row, dict) for row in rows)
            or tuple(row.get("one_way_bps") for row in rows) != COST_TIERS
            or any(type(row["one_way_bps"]) is not int for row in rows)):
        raise ValueError("FALSIFICATION_STRESS_SCOPE")
    results = []
    for row in rows:
        returns = {}
        for name in ("signal_rule", "constant_invested", "flat_cash_assumed_zero_interest"):
            cell = row.get(name)
            if not isinstance(cell, dict) or type(cell.get("interval_count")) is not int or cell["interval_count"] != n:
                raise ValueError("FALSIFICATION_INTERVAL_MISMATCH")
            v = cell.get("net_price_change_pct")
            exposure = cell.get("invested_intervals")
            if (type(v) not in {float, int} or not math.isfinite(v) or v <= -100
                    or type(exposure) is not int or not 0 <= exposure <= n):
                raise ValueError("FALSIFICATION_METRIC_INVALID")
            if ((name == "flat_cash_assumed_zero_interest" and (v != 0 or exposure != 0))
                    or (name == "constant_invested" and exposure != n)):
                raise ValueError("FALSIFICATION_BASELINE_INVALID")
            returns[name] = v
        vs_hold = returns["signal_rule"] - returns["constant_invested"]
        vs_cash = returns["signal_rule"] - returns["flat_cash_assumed_zero_interest"]
        if not math.isfinite(vs_hold) or not math.isfinite(vs_cash):
            raise ValueError("FALSIFICATION_MARGIN_NONFINITE")
        results.append({"one_way_bps": row["one_way_bps"], "net_price_pct": returns,
                        "signal_minus_hold_percentage_points": vs_hold,
                        "signal_minus_cash_percentage_points": vs_cash,
                        "dominates_both": vs_hold > 0 and vs_cash > 0})
    failed = [row["one_way_bps"] for row in results if not row["dominates_both"]]
    return {"criterion": CRITERION,
            "conditional_outcome": "FALSIFIED_CONDITIONAL" if failed else "NOT_FALSIFIED_THIS_CONTROL",
            "failed_cost_tiers": failed, "test_intervals": n,
            "first_entry_open": test.get("first_entry_open"), "terminal_open": test.get("terminal_open"),
            "comparisons": results, "statistical_validation": False,
            "historically_predeclared": False, "representative_sample": False,
            "total_return": False, "actual_costs_verified": False,
            "pit_safe": False, "decision_authority": False, "execution_allowed": False}


def verify_factor_lagged_profile(market: dict, factor: dict, diagnostic: dict) -> dict:
    """Recompute all lagged allocations and fee paths independently of momentum_metrics.

    Use the serialized factor only where its sign is consistent with exact
    observed close comparisons. Decimal arithmetic is an independent diagnostic
    oracle, not a model of real executable fills or historical availability.
    """
    assess_test_segment(diagnostic)
    bars, factors = market.get("bars"), factor.get("records")
    if (not isinstance(bars, list) or not isinstance(factors, list)
            or len(bars) != len(factors) or len(bars) < 242
            or not all(isinstance(row, dict) for row in [*bars, *factors])):
        raise ValueError("FALSIFICATION_LAGGED_INPUT")
    dates = []
    opens = []
    closes = []
    symbol = market.get("symbol")
    if not isinstance(symbol, str) or not symbol:
        raise ValueError("FALSIFICATION_LAGGED_IDENTITY")
    for bar, row in zip(bars, factors, strict=True):
        day = market_daily_label(bar.get("date"))
        if row.get("date") != day or row.get("symbol") != symbol:
            raise ValueError("FALSIFICATION_LAGGED_IDENTITY")
        dates.append(day)
        for key, dest in (("open", opens), ("close", closes)):
            v = bar.get(key)
            if (type(v) not in {int, float} or not math.isfinite(v) or v <= 0
                    or type(row.get(key)) not in {int, float} or row[key] != v):
                raise ValueError("FALSIFICATION_LAGGED_PRICE")
            dest.append(Decimal(str(v)))
    if dates != sorted(set(dates)):
        raise ValueError("FALSIFICATION_LAGGED_DATE_ORDER")
    targets = []
    with localcontext() as ctx:
        ctx.prec = 50
        for i, row in enumerate(factors):
            v = row.get("rolling_return_20")
            if i < 20:
                if v is not None or "rolling_return_20" not in row:
                    raise ValueError("FALSIFICATION_LAGGED_WARMUP")
                targets.append(None)
                continue
            exact = closes[i] / closes[i - 20] - 1
            if (type(v) not in {int, float} or not math.isfinite(v)
                    or abs(Decimal(str(v)) - exact) > Decimal("0.000000001")):
                raise ValueError("FALSIFICATION_LAGGED_FACTOR_VALUE")
            if (v > 0) != (closes[i] > closes[i - 20]):
                raise ValueError("FALSIFICATION_LAGGED_SIGNAL_SIGN")
            targets.append(int(v > 0))
        # No current open or forward label enters the allocation at that open:
        # target at open[t] is based on the factor ending at close[t-1].
        n = len(bars) - 22
        a, b = 60 * n // 100, 80 * n // 100
        groups = (range(21, 21 + a - 1), range(21 + a + 1, 21 + b - 1),
                  range(21 + b + 1, len(bars) - 1))
        if (diagnostic.get("observations") != len(bars)
                or diagnostic.get("eligible_intervals_before_split") != n
                or diagnostic.get("purged_or_embargoed_intervals") != 4
                or diagnostic.get("split_percent") != [60, 20, 20]
                or diagnostic.get("purge") != 1 or diagnostic.get("embargo") != 1
                or diagnostic.get("signal") != "PRIOR_CLOSE_20_SESSION_RETURN_GT_ZERO"
                or diagnostic.get("return_interval") != "NEXT_OPEN_TO_FOLLOWING_OPEN"):
            raise ValueError("FALSIFICATION_LAGGED_SPLIT")
        verified = []
        for group, segment in zip(groups, diagnostic["segments"], strict=True):
            if (len(group) < 40 or segment.get("intervals") != len(group)
                    or segment.get("first_entry_open") != dates[group.start]
                    or segment.get("terminal_open") != dates[group.stop]):
                raise ValueError("FALSIFICATION_LAGGED_SEGMENT_BOUNDARY")
            costs = segment.get("stress")
            if (not isinstance(costs, list) or not all(isinstance(row, dict) for row in costs)
                    or tuple(row.get("one_way_bps") for row in costs) != COST_TIERS
                    or any(type(row["one_way_bps"]) is not int for row in costs)):
                raise ValueError("FALSIFICATION_LAGGED_COST_TIERS")
            allocation = [targets[t - 1] for t in group]
            for row in costs:
                fee = Decimal(row["one_way_bps"]) / Decimal(10000)
                for name, positions in (("signal_rule", allocation),
                        ("constant_invested", [1] * len(group)),
                        ("flat_cash_assumed_zero_interest", [0] * len(group))):
                    wealth = peak = Decimal(1)
                    drawdown = Decimal(0)
                    previous = turnover = 0
                    for t, position in zip(group, positions, strict=True):
                        change = abs(position - previous)
                        turnover += change
                        wealth *= 1 - fee * change
                        drawdown = max(drawdown, 1 - wealth / peak)
                        if position:
                            wealth *= opens[t + 1] / opens[t]
                        peak = max(peak, wealth)
                        drawdown = max(drawdown, 1 - wealth / peak)
                        previous = position
                    turnover += previous
                    wealth *= 1 - fee * previous
                    drawdown = max(drawdown, 1 - wealth / peak)
                    actual = row.get(name)
                    if not isinstance(actual, dict):
                        raise ValueError("FALSIFICATION_LAGGED_METRIC_MISSING")
                    counts = {"unit_weight_turnover": turnover,
                              "invested_intervals": sum(positions), "interval_count": len(group)}
                    if any(type(actual.get(k)) is not int or actual[k] != v
                           for k, v in counts.items()):
                        raise ValueError("FALSIFICATION_LAGGED_ALLOCATION_MISMATCH")
                    values = {"net_price_change_pct": float((wealth - 1) * 100),
                              "max_observed_open_drawdown_pct": float(drawdown * 100)}
                    if any(type(actual.get(k)) not in {int, float} or not math.isfinite(actual[k])
                           or not math.isfinite(v)
                           or not math.isclose(actual[k], v, abs_tol=1e-8, rel_tol=1e-11)
                           for k, v in values.items()):
                        raise ValueError("FALSIFICATION_LAGGED_ARITHMETIC_MISMATCH")
            verified.append({"segment": segment["segment"], "intervals": len(group),
                             "allocation_count": sum(allocation),
                             "first_entry_open": dates[group.start],
                             "terminal_open": dates[group.stop]})
    return {"status": "MATCH", "signal_source": "SERIALIZED_FACTOR_WITH_EXACT_CLOSE_SIGN_CHECK",
            "signal_lag_sessions": 1, "segments": verified, "cost_tiers": list(COST_TIERS),
            "baseline_metric_cells_verified": 27, "historical_vintage_verified": False,
            "actual_costs_verified": False, "pit_safe": False, "decision_authority": False}
