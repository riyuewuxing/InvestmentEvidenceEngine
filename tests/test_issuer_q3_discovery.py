import json
from datetime import UTC, datetime

import pytest

from investment_evidence_engine.issuer_disclosure_index import discover_q3


def test_q3_discovery_preserves_multiple_versions_without_selecting():
    def row(aid, suffix, title="2026年第三季度报告"):
        return {"secCode": "000035", "orgId": "org1", "announcementId": aid,
                "announcementTitle": title + suffix,
                "adjunctUrl": f"finalpage/2026-10-30/{aid}.PDF",
                "announcementTime": int(datetime.fromisoformat("2026-10-30T00:00:00+08:00").timestamp()*1000)}
    raw = json.dumps({"announcements": [row("123", "", "中国天楹：2026年三季度报告"), row("124", "（更正后）")],
                      "totalAnnouncement": 2}).encode()
    result = discover_q3(raw, "org1", datetime(2026, 11, 26, tzinfo=UTC))
    assert result["candidate_count"] == 2
    assert not result["body_observed"]
    assert not result["revision_universe_complete"]
    assert all(not item["first_availability_verified"] for item in result["candidates"])


def test_q3_zero_match_is_not_absence_proof():
    raw = json.dumps({"announcements": [], "totalAnnouncement": 0}).encode()
    result = discover_q3(raw, "org1", datetime(2026, 11, 26, tzinfo=UTC))
    assert result["discovery_status"] == "NO_MATCH_IN_OBSERVED_WINDOW"
    assert not result["revision_universe_complete"]
    assert not result["body_observed"]


def test_q3_invalid_attachment_day_is_rejected():
    row = {"secCode": "000035", "orgId": "org1", "announcementId": "123",
           "announcementTitle": "2026年第三季度报告",
           "adjunctUrl": "finalpage/2026-13-99/123.PDF",
           "announcementTime": int(datetime.fromisoformat("2026-10-30T00:00:00+08:00").timestamp()*1000)}
    raw = json.dumps({"announcements": [row], "totalAnnouncement": 1}).encode()
    with pytest.raises(ValueError):
        discover_q3(raw, "org1", datetime(2026, 11, 26, tzinfo=UTC))
