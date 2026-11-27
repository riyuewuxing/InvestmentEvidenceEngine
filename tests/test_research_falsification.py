import copy
import json
from pathlib import Path

import pytest

from investment_evidence_engine.research_falsification import (
    COST_TIERS,
    assess_test_segment,
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
