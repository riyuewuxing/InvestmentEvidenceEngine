import json
from datetime import UTC, datetime

from investment_evidence_engine.issuer_disclosure_index import discover_q3


def test_q3_discovery_preserves_multiple_versions_without_selecting():
    def row(aid, suffix):
        return {"secCode": "000035", "orgId": "org1", "announcementId": aid,
                "announcementTitle": "2026年第三季度报告" + suffix,
                "adjunctUrl": f"finalpage/2026-10-30/{aid}.PDF",
                "announcementTime": int(datetime.fromisoformat("2026-10-30T00:00:00+08:00").timestamp()*1000)}
    raw = json.dumps({"announcements": [row("123", ""), row("124", "（更正后）")],
                      "totalAnnouncement": 2}).encode()
    result = discover_q3(raw, "org1", datetime(2026, 11, 26, tzinfo=UTC))
    assert result["candidate_count"] == 2
    assert not result["body_observed"]
    assert not result["revision_universe_complete"]
    assert all(not item["first_availability_verified"] for item in result["candidates"])
