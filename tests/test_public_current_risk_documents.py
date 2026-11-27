from investment_evidence_engine.public_current_risk_documents import parse_notice, purchase_summary, summarize


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


def test_purchase_summary_does_not_treat_commitment_as_drawdown():
    rows = [
        {"key": "purchase_plan", "status": "OBSERVED",
         "fields": {"plan_min_cny": 50000000, "plan_max_cny": 100000000, "loan_commitment_max_cny": 90000000}},
        {"key": "purchase_completion", "status": "OBSERVED",
         "fields": {"reported_purchase_cny": 99970400, "reported_purchased_shares": 21383824,
                    "group_before_shares": 590768945, "group_after_shares": 612152769}},
    ]
    report = purchase_summary(rows)
    assert report["status"] == "WARN"
    assert report["reported_purchase_plan_and_completion_match"]
    assert report["loan_actual_drawdown_cny"] is None
    assert report["issuer_received_purchase_cash_cny"] is None
    assert not report["decision_authority"]
    rows[1]["fields"]["group_after_shares"] += 1
    assert purchase_summary(rows)["status"] == "BLOCK"
