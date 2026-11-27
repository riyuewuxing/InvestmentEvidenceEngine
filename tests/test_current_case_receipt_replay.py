"""Replay actual public job log metadata; never treat log hashes as raw source bytes."""
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from investment_evidence_engine.snapshot_integrity import strict_json_loads

FIXTURE = Path(__file__).parents[1] / "fixtures/current_case/observed_000035_20261127.json"


def read_receipts():
    data = strict_json_loads(FIXTURE.read_bytes())
    assert data["scope"] == "PUBLIC_CASE_OBSERVED_LOG_METADATA_ONLY"
    assert data["raw_vendor_bodies_retained"] is False
    assert data["decision_authority"] is False
    assert data["execution_allowed"] is False
    out = {}
    for key, receipt in data["receipts"].items():
        prefix, content = receipt["line"].split(" " + receipt["marker"] + " ", 1)
        logged = datetime.fromisoformat(prefix)
        obj = strict_json_loads(content.encode())
        observed = datetime.fromisoformat(obj.get("observed_cutoff", obj.get("retrieved_at")))
        assert observed.utcoffset() is not None and observed <= logged
        if key == "prior_q3":
            assert obj["financial"]["decision_authority"] is False
            assert obj["pressure"]["decision_authority"] is False
            assert obj["pit_safe"] is False
        else:
            assert obj["decision_authority"] is False
        out[key] = obj
    return data, out


def test_actual_public_case_identity_and_time_join():
    _, r = read_receipts()
    index = r["risk_index"]
    docs = r["risk_documents"]["notices"]
    assert index["status"] == "OBSERVED" and index["parent_rehash"] == "MATCH"
    paths = {item["attachment"] for item in index["records"]}
    assert {doc["url"].split("static.cninfo.com.cn/")[1] for doc in docs} == paths
    assert all(doc["parent_rehash"] == "MATCH" and doc["raw_body_retained"] is False for doc in docs)
    assert all(datetime.fromisoformat(doc["retrieved_at"]) >= datetime.fromisoformat(index["retrieved_at"])
               for doc in docs)
    assert not any(item["first_availability_verified"] for item in index["records"])


def test_actual_public_case_share_pledge_and_capitalization_are_distinct():
    _, r = read_receipts()
    risk = {doc["key"]: doc["fields"] for doc in r["risk_documents"]["notices"]}
    purchase = {doc["key"]: doc["fields"] for doc in r["controller_purchase"]["notices"]}
    p, rel, comp = risk["pledge"], risk["release"], purchase["purchase_completion"]
    assert comp["group_before_shares"] + comp["reported_purchased_shares"] == comp["group_after_shares"]
    assert comp["group_after_shares"] == p["group_holdings_shares"] == rel["group_holdings_shares"]
    assert p["before_group_pledged_shares"] + p["new_pledged_shares"] == p["after_group_pledged_shares"]
    assert p["after_group_pledged_shares"] - rel["released_shares"] == rel["after_group_pledged_shares"]
    for doc in (p, rel):
        ratio = (Decimal(doc["after_group_pledged_shares"]) * 100 / doc["group_holdings_shares"])
        assert ratio.quantize(Decimal("0.01")) == Decimal(doc["reported_group_pct"])
    proxy = r["shares"]["proxy"]
    assert proxy["share_count_as_of"] == "2026-10-30"
    assert proxy["equity_as_of"] == "2026-09-30"
    assert proxy["price_session"] == "2026-11-27"
    assert proxy["equity_raw_sha256"] == r["prior_q3"]["sha256"]
    rows = r["prior_q3"]["pressure"]["periods"][0]["rows_cny"]
    assert proxy["equity_cny"] == rows["parent_equity"]
    price = [x for x in r["price"]["terminal_observations"] if x["symbol"] == "000035"]
    assert len(price) == 2 and {x["normalized_sha256"] for x in price} == {proxy["price_normalized_sha256"]}
    assert all(Decimal(str(x["terminal"][1])) == Decimal(proxy["price_cny"]) for x in price)
    cap = Decimal(proxy["price_cny"]) * proxy["shares"]
    assert cap == Decimal(proxy["conditional_capitalization_cny"])
    assert (cap / Decimal(proxy["equity_cny"])).quantize(Decimal("0.0001")) == Decimal(proxy["conditional_pb"])
    assert not proxy["current_share_count_verified"]
    assert r["controller_purchase"]["loan_actual_drawdown_cny"] is None
    assert not r["risk_documents"]["guarantees_additive_to_consolidated_debt"]


def test_actual_public_case_alternative_and_procurement_partial_source_limits():
    _, r = read_receipts()
    a = r["alternative_supplement"]
    t = [x for x in r["price"]["terminal_observations"] if x["symbol"] == "510300"]
    assert len(t) == 1 and t[0]["provider"] == "tencent"
    assert a["provider"] == "eastmoney" and a["normalized_sha256"] == t[0]["normalized_sha256"]
    assert a["row_count"] == t[0]["row_count"] == a["calendar_session_count"] == 25
    assert a["exact_prior_tencent_projection_match"] and a["observed_calendar_sessions_match"]
    assert not a["source_independence_verified"] and not a["historical_vintage_verified"]
    assert r["price"]["status"] == "BLOCK"
    assert r["procurement"]["status"] == "BLOCK"
    assert r["procurement"]["issuer_share_of_contract_cny"] is None
    assert r["procurement"]["received_cash_cny"] is None
    assert not r["procurement"]["actual_signed_contract_observed"]


def test_actual_public_case_replay_is_not_formal_admission():
    _, r = read_receipts()
    for key, value in r.items():
        if key == "prior_q3":
            assert value["financial"]["decision_authority"] is False
            assert value["pressure"]["decision_authority"] is False
        else:
            assert value["decision_authority"] is False
        assert value.get("historical_pit", False) is False
        assert value.get("execution_allowed", False) is False
    # The tested data are log metadata. A caller cannot create a raw source receipt by renaming a hash.
    assert r["risk_documents"]["durable_original_bytes_verified"] is False
    assert r["prior_q3"]["raw_body_retained"] is False
    assert r["shares"]["raw_body_retained"] is False
