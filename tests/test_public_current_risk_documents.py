from investment_evidence_engine.public_current_risk_documents import parse_notice, summarize


def test_pledge_not_promoted_without_all_anchors():
    result = parse_notice("pledge", ("证券代码:000035 中国天楹股份有限公司",))
    assert result["anchor_checks"]["identity"]
    assert result["fields"] is None


def test_partial_bridge_and_guarantee_not_admitted():
    result = summarize([{"key": "pledge", "status": "BLOCK", "fields": None}])
    assert result["status"] == "BLOCK"
    assert result["pledge_snapshot_arithmetic_match"] is None
    assert not result["decision_authority"]
    assert not result["guarantees_additive_to_consolidated_debt"]
