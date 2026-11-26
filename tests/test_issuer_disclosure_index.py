import json
from datetime import UTC, datetime

import pytest

from investment_evidence_engine.issuer_disclosure_index import WINDOWS, parse_index, select_org

NOW = datetime(2026, 11, 26, tzinfo=UTC)


def body(**changes):
    row = {"secCode": "000035", "orgId": "org1", "announcementId": "1223370914",
           "announcementTitle": "2024年年度报告摘要",
           "adjunctUrl": "finalpage/2025-04-29/1223370914.PDF",
           "announcementTime": int(datetime.fromisoformat("2025-04-29T00:00:00+08:00").timestamp()*1000)}
    row.update(changes)
    return json.dumps({"announcements": [row], "totalAnnouncement": 1}).encode()


def test_midnight_not_first_availability():
    record = parse_index(body(), "org1", WINDOWS[0], NOW)["target_records"]["annual_2024"]
    assert record["platform_midnight"] is True
    assert record["first_availability_verified"] is False


@pytest.mark.parametrize("changes", [
    {"secCode": "000001"}, {"orgId": "org2"}, {"announcementId": "unknown"},
    {"adjunctUrl": "finalpage/2025-04-28/1223370914.PDF"}, {"announcementTime": True},
    {"announcementTitle": "other"}, {"announcementTime": 1},
])
def test_index_rejects_bad_target(changes):
    with pytest.raises(ValueError):
        parse_index(body(**changes), "org1", WINDOWS[0], NOW)


def test_incomplete_page_rejected():
    with pytest.raises(ValueError, match="INDEX_PAGE_COUNT"):
        parse_index(body().replace(b'"totalAnnouncement": 1', b'"totalAnnouncement": 2'), "org1", WINDOWS[0], NOW)


def test_directory_identity():
    assert select_org(b'{"stockList":[{"code":"000035","orgId":"org1"}]}') == "org1"
    with pytest.raises(ValueError):
        select_org(b'{"stockList":[{"code":"000035","orgId":"org1"},{"code":"000035","orgId":"org2"}]}')


def test_directory_entry_uses_nonempty_worker_argument(monkeypatch):
    from investment_evidence_engine import issuer_disclosure_index as index
    from investment_evidence_engine.bounded_worker import WorkerResult

    def fake_worker(command, **kwargs):
        assert all(command)
        assert command[-2:] == ("directory", "-")
        return WorkerResult("WATCHDOG_TIMEOUT")

    monkeypatch.setattr(index, "run_json_worker", fake_worker)
    report = index.run_control()
    assert report["status"] == "BLOCK"
    assert len(report["observations"]) == 1
    assert report["observations"][0]["worker_status"] == "WATCHDOG_TIMEOUT"
