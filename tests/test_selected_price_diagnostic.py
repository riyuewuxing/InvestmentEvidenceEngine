import hashlib
import json

import pytest

from investment_evidence_engine.contracts import canonical_sha256
from investment_evidence_engine.market_calendar import scheduled_days
from investment_evidence_engine.selected_price_diagnostic import (
    FIRST,
    SCOPE,
    evaluate_market_payload,
    verify_selection,
)

END = SCOPE.replace(day=25)


def scan():
    record = {"code": "600001", "asset": "600001", "latest_price": 10}
    payload = {"candidates": [record], "candidate_count": 1,
               "ranking_semantics": "RESEARCH_PRIORITY_NOT_RETURN_FORECAST",
               "research_only": True, "pit_safe": False, "decision_authority": False,
               "input_mode": "LIVE_MARKET_UNIVERSE", "rule_origin": "SYSTEM_RESEARCH_FILTER",
               "rules": [{"field": "latest_price", "operator": "GE", "threshold": 10, "weight": 1}],
               "dependency_evidence": {"as_of": SCOPE.isoformat(), "source": "public_market_data",
                                       "market": "CN_A", "asset_type": "STOCK", "status": "WARN"}}
    raw = json.dumps(payload).encode()
    receipt = {"status": "PUBLIC_PACKET_AND_ATTACHMENT_REHASHED",
               "as_of": SCOPE.isoformat(), "deterministic_scan_replay": "MATCH",
               "materialized_attachment_rehash": "MATCH", "decision_authority": False,
               "private_admission_verified": False,
               "candidate_record_sha256": canonical_sha256(record),
               "artifacts": {"opportunity-scan.json": {"sha256": hashlib.sha256(raw).hexdigest(),
                                                       "size_bytes": len(raw)}}}
    return raw, receipt


def test_exact_first_record_required():
    raw, receipt = scan()
    assert verify_selection(raw, receipt, ["sh.600001"]) == "600001"
    with pytest.raises(ValueError, match="FIRST_RECORD_OUTSIDE_REFERENCE"):
        verify_selection(raw, receipt, ["sh.600002"])
    with pytest.raises(ValueError, match="SCAN_BYTES_MISMATCH"):
        verify_selection(raw + b" ", receipt, ["sh.600001"])
    receipt["candidate_record_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="RECORD_MISMATCH"):
        verify_selection(raw, receipt, ["sh.600001"])


def payload():
    rows = [x.day for x in scheduled_days(FIRST, END) if x.is_trading_day]
    return {"symbol": "600001", "start": FIRST.isoformat(), "end": END.isoformat(),
            "as_of": SCOPE.isoformat(), "adjust": "", "history_end_offset_days": 1,
            "pit_safe": False, "decision_authority": False, "historical_vintage_verified": False,
            "crosscheck": {"status": "MATCH_OBSERVED_ROWS", "tolerance": 0.001,
                           "latest_common_date": END.isoformat(), "overlap_rows": len(rows),
                           "left_only_dates": 0, "right_only_dates": 0, "max_relative_price_diff": 0.0},
            "providers": [{"upstream": "eastmoney", "status": "OBSERVED"},
                          {"upstream": "tencent", "status": "OBSERVED", "raw_body_parent_rehash": "MATCH"}],
            "bars": [{"date": d.isoformat(), "open": 10, "close": 10, "high": 11, "low": 9, "volume": 1000}
                     for d in rows]}


def test_same_scope_dual_route_diagnostic_only():
    report = evaluate_market_payload(payload(), symbol="600001")
    assert report["status"] == "RETROSPECTIVE_PRICE_DIAGNOSTIC_ONLY"
    assert not report["pit_safe"] and not report["forecast_validated"]


@pytest.mark.parametrize("fault", ["symbol", "future", "adjusted", "single", "receipt", "missing"])
def test_missing_or_conflicting_market_observation_blocks(fault):
    data = payload()
    if fault == "symbol":
        data["symbol"] = "600002"
    elif fault == "future":
        data["end"] = SCOPE.isoformat()
    elif fault == "adjusted":
        data["adjust"] = "qfq"
    elif fault == "single":
        data["crosscheck"]["status"] = "SINGLE_SOURCE"
    elif fault == "receipt":
        data["providers"][1]["raw_body_parent_rehash"] = "UNKNOWN"
    else:
        data["bars"].pop(10)
    with pytest.raises(ValueError):
        evaluate_market_payload(data, symbol="600001")


@pytest.mark.parametrize("value", [None, True, -0.1, 0.00101, float("nan"), float("inf")])
def test_claimed_match_requires_bounded_actual_difference(value):
    data = payload()
    data["crosscheck"]["max_relative_price_diff"] = value
    with pytest.raises(ValueError, match="PRICE_CROSSCHECK_REQUIRED"):
        evaluate_market_payload(data, symbol="600001")
