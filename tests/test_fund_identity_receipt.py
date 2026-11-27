import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from investment_evidence_engine.fund_identity_receipt import (
    MARKER,
    SELECTION,
    parse_identity_receipt,
)

SHA = "a" * 40
NOW = datetime(2026, 11, 27, 12, tzinfo=UTC)


def report():
    start, end = "2026-11-27T10:00:00+00:00", "2026-11-27T10:00:02+00:00"
    fields = {
        "code": "123456", "share_class_codes": ["123456", "123457"],
        "product_kind": "ETF_FEEDER_FUND", "document_day": "2025-11-05",
        "manager_name_reported": "测试经理", "manager_start_reported": "2024-07-10",
        "benchmark": "示例指数", "management_rate_pct": "0.50", "custody_rate_pct": "0.10",
        "fee_basis": "NAV_EXCLUDING_TARGET_ETF_ASSETS",
        "estimated_operation_rate_pct": {"123456": "0.61", "123457": "0.71"},
        "current_notice_chain_verified": False, "actual_cost_verified": False,
        "actual_dealing_verified": False, "historical_first_availability_verified": False,
        "formal_admission": False, "candidate_rank_membership_verified": False,
    }
    row = {"code": "123456", "url": "https://static.cninfo.com.cn/finalpage/2025-11-05/123456.PDF",
           "status": "OBSERVED", "worker_status": "OK", "parent_rehash": "MATCH",
           "raw_body_retained": False, "bytes": 100, "page_count": 4, "sha256": "b" * 64,
           "started_at": start, "finished_at": end, "retrieved_at": "2026-11-27T10:00:01+00:00",
           "fields": fields}
    return {"status": "WARN", "selection": SELECTION, "research_only": True, "formal_admission": False,
            "decision_authority": False, "execution_allowed": False, "executor_commit": SHA,
            "started_at": start, "finished_at": end, "records": [row]}


def parse(r):
    return parse_identity_receipt("2026-11-27T10:00:03Z " + MARKER + " " + json.dumps(r),
                                  expected_commit=SHA, now=NOW)


def test_report_metadata_does_not_become_current_or_admitted_and_classes_separate():
    out = parse(report())
    assert set(out) == {"123456", "123457"}
    assert out["123456"]["estimated_operation_rate_pct_reported"] == "0.61"
    assert out["123457"]["estimated_operation_rate_pct_reported"] == "0.71"
    assert out["123457"]["product_main_code"] == "123456"
    assert out["123457"]["document_day"] == "2025-11-05"
    assert not out["123457"]["formal_admission"]
    assert not out["123457"]["receiver_original_bytes_verified"]
    assert not out["123457"]["candidate_rank_membership_verified"]


@pytest.mark.parametrize("field,value", [
    ("candidate_rank_membership_verified", True), ("formal_admission", True),
    ("fee_basis", "FUND_ASSET_NAV"), ("product_kind", "INDEX_ETF"),
    ("share_class_codes", ["123456", "123456"]), ("document_day", "2025-11-06"),
    ("manager_start_reported", "2026-11-28"), ("management_rate_pct", "nan"),
    ("estimated_operation_rate_pct", {"123456": "0.6"}),
])
def test_inconsistent_metadata_blocks(field, value):
    r = report()
    r["records"][0]["fields"][field] = value
    with pytest.raises(ValueError):
        parse(r)


@pytest.mark.parametrize("field,value", [
    ("raw_body_retained", True), ("parent_rehash", "MISMATCH"),
    ("sha256", "bad"), ("retrieved_at", "2026-11-28T10:00:00Z"),
    ("url", "https://example.com/finalpage/2025-11-05/123456.PDF"),
])
def test_transport_scope_blocks(field, value):
    r = report()
    r["records"][0][field] = value
    with pytest.raises(ValueError):
        parse(r)


def test_duplicate_class_across_records_is_not_silently_selected():
    r = report()
    r["records"].append(r["records"][0])
    with pytest.raises(ValueError):
        parse(r)


def test_replay_exact_observed_public_metadata():
    fixture = Path(__file__).resolve().parents[1] / "controls/fund-identity-20261127-metadata.json"
    r = json.loads(fixture.read_text(encoding="utf-8"))
    rows = parse_identity_receipt(r["log_line"], expected_commit=r["executor_commit"], now=NOW)
    assert set(rows) == {"510300", "161907", "015558", "013125"}
    assert rows["510300"]["product_kind_reported"] == "INDEX_ETF"
    assert rows["510300"]["tracking_error_target_pct_reported"] == "2"
    assert rows["510300"]["listed_exchange_reported"] == "SSE"
    assert rows["161907"]["listed_exchange_reported"] is None
    assert rows["161907"]["product_kind_reported"] == "ETF_FEEDER_FUND"
    assert rows["161907"]["conversion_day_reported"] == "2024-07-10"
    assert rows["015558"]["estimated_operation_rate_pct_reported"] == "0.71"
    assert rows["013125"]["document_day"] == "2025-06-30"
    assert all(not row["formal_admission"] and not row["candidate_rank_membership_verified"] for row in rows.values())

def test_active_identity_requires_separate_listing_and_never_imputes_cost_or_tracking():
    r = report()
    x = r["records"][0]
    x["fields"].update(product_kind="ACTIVE_ETF", share_class_codes=["123456"],
                       listed_exchange_reported="SZSE", manager_start_reported=None,
                       fee_basis="FUND_ASSET_NAV", estimated_operation_rate_pct={"123456": None},
                       not_index_tracking_objective=True)
    with pytest.raises((ValueError, KeyError)):
        parse(r)
    listing = dict(x, code="123456_listing", page_count=1,
                   url="https://static.cninfo.com.cn/finalpage/2026-11-23/123457.PDF")
    listing["fields"] = {"code": "123456", "product_kind": "ACTIVE_ETF",
                         "document_day": "2026-11-23", "listing_day_reported": "2026-11-23",
                         "listed_exchange_reported": "SZSE", "actual_dealing_verified": False,
                         "formal_admission": False}
    x["listing_notice"] = listing
    row = parse(r)["123456"]
    assert row["product_kind_reported"] == "ACTIVE_ETF"
    assert row["listing_day_reported"] == "2026-11-23"
    assert row["manager_start_reported"] is None
    assert row["estimated_operation_rate_pct_reported"] is None
    assert row["tracking_error_target_pct_reported"] is None
    listing["fields"]["listed_exchange_reported"] = "SSE"
    with pytest.raises(ValueError):
        parse(r)

def test_replay_actual_active_etf_identity_listing_and_no_annual_history():
    fixture = Path(__file__).resolve().parents[1] / "controls/active-etf-identity-20261127-metadata.json"
    r = json.loads(fixture.read_text(encoding="utf-8"))
    rows = parse_identity_receipt(r["log_line"], expected_commit=r["executor_commit"], now=NOW)
    assert set(rows) == {"158909"}
    row = rows["158909"]
    assert row["product_kind_reported"] == "ACTIVE_ETF"
    assert row["document_day"] == "2026-10-20"
    assert row["listing_day_reported"] == "2026-11-23"
    assert row["listed_exchange_reported"] == "SZSE"
    assert row["manager_start_reported"] is None
    assert row["estimated_operation_rate_pct_reported"] is None
    assert row["management_rate_pct_reported"] == "1.00"
    assert row["custody_rate_pct_reported"] == "0.15"
    assert row["tracking_error_target_pct_reported"] is None
    assert row["formal_admission"] is False
