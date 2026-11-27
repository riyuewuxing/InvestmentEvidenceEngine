import json
from datetime import UTC, datetime

import pytest

from investment_evidence_engine.fund_identity_receipt import MARKER, SELECTION, parse_identity_receipt

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
