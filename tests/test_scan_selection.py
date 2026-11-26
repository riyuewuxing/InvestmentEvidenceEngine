import copy
import json

import pytest

from investment_evidence_engine.scan_selection import select_scan_record

DAY = "2026-11-26"
BASE = {"candidates": [{"code": "600519", "asset": "600519", "name": "Public fixture",
                        "latest_price": 10.0, "matched_rule_count": 1, "research_priority_score": 1}],
        "candidate_count": 1, "screened_count": 20, "research_only": True, "pit_safe": False,
        "decision_authority": False, "input_mode": "LIVE_MARKET_UNIVERSE",
        "ranking_semantics": "RESEARCH_PRIORITY_NOT_RETURN_FORECAST",
        "rule_origin": "SYSTEM_RESEARCH_FILTER",
        "rules": [{"field": "latest_price", "operator": "GE", "threshold": 1, "weight": 1}],
        "dependency_evidence": {"operation_id": "market-universe", "kind": "MARKET_UNIVERSE",
                                "as_of": DAY, "market": "CN_A", "asset_type": "STOCK",
                                "source": "public_market_data", "status": "WARN",
                                "provider": "akshare", "primary_provider": "akshare_sina",
                                "quote_trade_date_status": "UNKNOWN",
                                "listing_crosscheck": {"status": "UNAVAILABLE"},
                                "warnings": ["MARKET_UNIVERSE_QUOTE_DATE_UNVERIFIED"]}}


def raw(data):
    return json.dumps(data, ensure_ascii=False).encode()


def test_production_shape_and_explicit_unknowns():
    assert select_scan_record(raw(BASE), DAY)["code"] == "600519"


@pytest.mark.parametrize("mode", ["private_metadata", "private_listing", "wrong_kind", "wrong_id",
                                  "bad_warning", "bool_count", "too_many_matches", "screened"])
def test_shared_selector_rejects_untyped_or_extra_metadata(mode):
    data = copy.deepcopy(BASE)
    dep = data["dependency_evidence"]
    if mode == "private_metadata":
        dep["account"] = "secret"
    elif mode == "private_listing":
        dep["listing_crosscheck"]["position"] = 1
    elif mode == "wrong_kind":
        dep["kind"] = "TEST_SUITE"
    elif mode == "wrong_id":
        dep["operation_id"] = "../bad"
    elif mode == "bad_warning":
        dep["warnings"] = [{"cash": 1}]
    elif mode == "bool_count":
        data["candidate_count"] = True
    elif mode == "too_many_matches":
        data["candidates"][0]["matched_rule_count"] = 2
    else:
        data["screened_count"] = 0
    with pytest.raises(ValueError):
        select_scan_record(raw(data), DAY)
