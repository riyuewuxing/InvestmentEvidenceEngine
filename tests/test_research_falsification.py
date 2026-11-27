import copy
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from investment_evidence_engine.momentum_profile import momentum_profile
from investment_evidence_engine.research_falsification import (
    COST_TIERS,
    assess_test_segment,
    verify_factor_lagged_profile,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/research_profile/observed_20261126_000035_diagnostic.json"


def observed():
    # Prior derived metrics only; not newly captured rows or a historical preregistration.
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_prior_actual_control_cannot_claim_joint_dominance():
    report = assess_test_segment(observed())
    assert report["conditional_outcome"] == "FALSIFIED_CONDITIONAL"
    assert report["failed_cost_tiers"] == list(COST_TIERS)
    assert all(r["signal_minus_cash_percentage_points"] < 0 for r in report["comparisons"])
    assert not report["pit_safe"] and not report["statistical_validation"]


def test_no_failure_is_not_validation_and_equality_refutes():
    d = observed()
    for row in d["segments"][-1]["stress"]:
        row["signal_rule"]["net_price_change_pct"] = 30.0
    report = assess_test_segment(d)
    assert report["conditional_outcome"] == "NOT_FALSIFIED_THIS_CONTROL"
    assert not report["statistical_validation"] and not report["decision_authority"]
    d["segments"][-1]["stress"][0]["signal_rule"]["net_price_change_pct"] = 0
    assert assess_test_segment(d)["failed_cost_tiers"] == [10]


@pytest.mark.parametrize("mode", ["missing", "duplicates", "wrong_count", "nan", "cash",
                                  "pit", "selection", "wrong_split", "boolean"])
def test_no_silent_partial_comparisons(mode):
    d = copy.deepcopy(observed())
    rows = d["segments"][-1]["stress"]
    if mode == "missing":
        rows.pop()
    elif mode == "duplicates":
        rows[1]["one_way_bps"] = 10
    elif mode == "wrong_count":
        rows[0]["signal_rule"]["interval_count"] += 1
    elif mode == "nan":
        rows[0]["signal_rule"]["net_price_change_pct"] = float("nan")
    elif mode == "cash":
        rows[0]["flat_cash_assumed_zero_interest"]["net_price_change_pct"] = .01
    elif mode == "pit":
        d["pit_safe"] = True
    elif mode == "selection":
        d["model_selection_performed"] = True
    elif mode == "wrong_split":
        d["segments"].reverse()
    else:
        rows[0]["signal_rule"]["net_price_change_pct"] = True
    with pytest.raises(ValueError, match="FALSIFICATION_"):
        assess_test_segment(d)


def factor_fixture():
    # Synthetic chronology with alternating trends, not historical market evidence.
    days = tuple(date(2025, 1, 1) + timedelta(days=i) for i in range(459))
    prices = [100 + (i % 57) / 10 + i / 200 for i in range(len(days))]
    opens = [price + (i % 3) / 10 for i, price in enumerate(prices)]
    bars = [{"date": d.isoformat() + "T00:00:00.000", "open": o, "close": c}
            for d, o, c in zip(days, opens, prices, strict=True)]
    factors = [{**bar, "date": day.isoformat(), "symbol": "600519",
                "rolling_return_20": None if i < 20 else round(prices[i] / prices[i-20] - 1, 10)}
               for i, (bar, day) in enumerate(zip(bars, days, strict=True))]
    return {"symbol": "600519", "bars": bars}, {"records": factors}, momentum_profile(days, prices, opens)


def test_independent_factor_lagged_profile_recomputes_all_27_cells():
    market, factor, d = factor_fixture()
    receipt = verify_factor_lagged_profile(market, factor, d)
    assert receipt["status"] == "MATCH" and receipt["signal_lag_sessions"] == 1
    assert receipt["baseline_metric_cells_verified"] == 27
    assert receipt["segments"][-1]["intervals"] == 87 and not receipt["pit_safe"]


@pytest.mark.parametrize("mode", ["warmup", "lookahead", "sign", "wrong_price", "wrong_date",
    "split", "boundary", "cost", "allocation", "turnover", "return", "drawdown", "baseline"])
def test_lagged_profile_cannot_certify_resealed_wrong_computation(mode):
    market, factor, d = factor_fixture()
    row = d["segments"][0]["stress"][0]
    if mode == "warmup":
        factor["records"][0]["rolling_return_20"] = 0
    elif mode == "lookahead":
        factor["records"][80]["rolling_return_20"] = factor["records"][81]["rolling_return_20"]
    elif mode == "sign":
        factor["records"][40]["rolling_return_20"] *= -1
    elif mode == "wrong_price":
        factor["records"][1]["open"] += 1
    elif mode == "wrong_date":
        factor["records"][1]["date"] = factor["records"][2]["date"]
    elif mode == "split":
        d["purged_or_embargoed_intervals"] = 0
    elif mode == "boundary":
        d["segments"][1]["first_entry_open"] = d["segments"][0]["first_entry_open"]
    elif mode == "cost":
        d["segments"][0]["stress"].reverse()
    elif mode == "allocation":
        row["signal_rule"]["invested_intervals"] += 1
    elif mode == "turnover":
        row["signal_rule"]["unit_weight_turnover"] += 1
    elif mode == "return":
        row["signal_rule"]["net_price_change_pct"] += .01
    elif mode == "drawdown":
        row["signal_rule"]["max_observed_open_drawdown_pct"] += .01
    else:
        row["constant_invested"]["net_price_change_pct"] += .01
    with pytest.raises(ValueError, match="FALSIFICATION_LAGGED_"):
        verify_factor_lagged_profile(market, factor, d)
