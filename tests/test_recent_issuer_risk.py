import json
from datetime import UTC, datetime

import pytest

from investment_evidence_engine.issuer_disclosure_index import OBSERVED_ORG_ID, discover_recent_risk


def _row(**changes):
    return {"secCode": "000035", "orgId": OBSERVED_ORG_ID,
            "announcementId": "123", "announcementTitle": "关于控股股东部分股份解除质押的公告",
            "adjunctUrl": "finalpage/2026-11-25/123.PDF",
            "announcementTime": int(datetime(2026, 11, 24, 16, tzinfo=UTC).timestamp()*1000)} | changes


def _raw(rows):
    return json.dumps({"announcements": rows, "totalAnnouncement": len(rows)}).encode()


def test_recent_risk_window_binds_title_attachment_and_time():
    out = discover_recent_risk(_raw([_row()]), OBSERVED_ORG_ID, datetime(2026, 11, 27, tzinfo=UTC))
    assert len(out["release_candidates"]) == 1
    assert out["release_candidates"][0]["first_availability_verified"] is False
    assert out["revision_universe_complete"] is False


@pytest.mark.parametrize("changes", [{"secCode": "600000"}, {"adjunctUrl": "finalpage/2026-11-25/999.PDF"},
                                     {"announcementTime": True}])
def test_recent_risk_scope_rejects_mutated_identity(changes):
    with pytest.raises(ValueError):
        discover_recent_risk(_raw([_row(**changes)]), OBSERVED_ORG_ID, datetime(2026, 11, 27, tzinfo=UTC))


def test_recent_risk_duplicate_rejected():
    with pytest.raises(ValueError):
        discover_recent_risk(_raw([_row(), _row()]), OBSERVED_ORG_ID, datetime(2026, 11, 27, tzinfo=UTC))
