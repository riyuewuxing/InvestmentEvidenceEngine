import base64
import hashlib
import json

import pytest

from investment_evidence_engine.historical_archive_probe import (
    FIELDS,
    TARGETS,
    parse_cdx,
    verify_replay,
)

ORIGINAL = TARGETS["hk"][0]
BODY = b"%PDF-1.4\nexample\n%%EOF\n"
DIGEST = base64.b32encode(hashlib.sha1(BODY).digest()).decode()


def test_archive_candidate_exact_route_and_scope():
    rows = [FIELDS, ["20240901000000", ORIGINAL, "application/pdf", "200", DIGEST],
            ["20240830000000", ORIGINAL, "application/pdf", "200", DIGEST]]
    result = parse_cdx(json.dumps(rows).encode(), ORIGINAL)
    assert result["candidate"]["capture_stamp"] == "20240830000000"
    assert parse_cdx(b"[]", ORIGINAL)["status"] == "NO_CAPTURE_RETURNED"
    rows[2][1] = ORIGINAL.replace("https:", "http:")
    assert parse_cdx(json.dumps(rows).encode(), ORIGINAL)["eligible_count"] == 1
    rows[1][0] = "20250101000000"
    with pytest.raises(ValueError, match="TIMESTAMP_SCOPE"):
        parse_cdx(json.dumps(rows).encode(), ORIGINAL)


def test_archive_digest_and_capture_clock_required():
    candidate = {"capture_stamp": "20240830000000", "digest_sha1_base32": DIGEST}
    stamp = "Fri, 30 Aug 2024 00:00:00 GMT"
    result = verify_replay(BODY, candidate, stamp, hashlib.sha256(BODY).hexdigest())
    assert result["archive_digest_match"] and result["current_bytes_match"]
    assert not result["first_publication_verified"] and not result["pit_safe"]
    with pytest.raises(ValueError, match="MEMENTO"):
        verify_replay(BODY, candidate, None, "x")
    with pytest.raises(ValueError, match="DIGEST_MISMATCH"):
        verify_replay(BODY + b"x", candidate, stamp, "x")
