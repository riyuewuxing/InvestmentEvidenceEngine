"""Predeclared, price-only falsification of a fixed descriptive momentum rule.

This is not statistical validation, historical PIT, total return or trade advice.
It does not alter the sealed prospective experiment or select a new strategy.
"""
from __future__ import annotations

import math

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
