from investment_evidence_engine.public_procurement_chain import VisibleText, summarize


def test_script_content_not_visible():
    parser = VisibleText()
    parser.feed("<p>actual</p><script>not evidence</script><style>not evidence</style><p>visible</p>")
    assert " ".join(parser.parts) == "actual visible"


def test_partial_chain_never_grants_contract_or_cash():
    result = summarize([{"key": "award", "status": "OBSERVED", "fields": {"consortium_total_cny": 10}}])
    assert result["status"] == "BLOCK"
    assert result["issuer_share_of_contract_cny"] is None
    assert result["recognized_revenue_cny"] is None
    assert result["received_cash_cny"] is None
    assert not result["decision_authority"]
