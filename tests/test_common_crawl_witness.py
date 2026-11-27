import gzip
import json

import pytest

from investment_evidence_engine.common_crawl_witness import (
    TARGETS,
    digest32,
    parse_index,
    sha,
    verify_member,
)

COLLECTION = "CC-MAIN-2024-38"
URL = TARGETS["hk"][0]
PDF = b"%PDF-1.4\nsynthetic fixture only\n%%EOF\n"


def entry():
    return {"timestamp": "20240910100000", "url": URL, "status": "200",
            "mime": "application/pdf", "mime-detected": "application/pdf",
            "digest": digest32(PDF), "filename": "crawl-data/CC-MAIN-2024-38/segments/1234.5/warc/example.warc.gz",
            "offset": "99", "length": "100"}


def member(*, pdf=PDF, truncated=False, wrong_uri=False, wrong_block=False, wrong_payload=False):
    block = b"HTTP/1.1 200 OK\r\nContent-Type: application/pdf\r\nContent-Length: " + str(len(pdf)).encode() + b"\r\n\r\n" + pdf
    hdr = ("WARC/1.0\r\nWARC-Type: response\r\nWARC-Target-URI: " + (URL if not wrong_uri else "https://example.invalid/")
        + "\r\nWARC-Date: 2024-09-10T10:00:00Z\r\nContent-Type: application/http; msgtype=response\r\n"
        + "Content-Length: " + str(len(block)) + "\r\nWARC-Block-Digest: sha1:"
        + (digest32(b"x") if wrong_block else digest32(block)) + "\r\nWARC-Payload-Digest: sha1:"
        + (digest32(b"x") if wrong_payload else digest32(pdf)) + "\r\n"
        + ("WARC-Truncated: length\r\n" if truncated else "") + "\r\n").encode()
    raw = gzip.compress(hdr + block + b"\r\n\r\n")
    c = parse_index(json.dumps(entry()).encode(), kind="hk", collection=COLLECTION)["candidate"]
    c["length"] = len(raw)
    return raw, c


def test_exact_archive_witness_is_not_first_publication():
    raw, c = member()
    report, body = verify_member(raw, c, current_sha=sha(PDF))
    assert body == PDF and report["current_bytes_match"]
    assert report["capture_at"] == "2024-09-10T10:00:00+00:00"
    assert not report["pit_safe"] and not report["first_publication_verified"]
    assert not verify_member(raw, c, current_sha="0"*64)[0]["current_bytes_match"]


@pytest.mark.parametrize("mode", ["wrong_uri", "truncated", "wrong_block", "wrong_payload"])
def test_wrong_warc_identity_or_digest_fails(mode):
    raw, c = member(**{mode: True})
    with pytest.raises(ValueError, match="CC_"):
        verify_member(raw, c, current_sha=sha(PDF))


def test_concatenated_member_rejected():
    raw, c = member()
    raw += raw
    c["length"] = len(raw)
    with pytest.raises(ValueError, match="CC_MEMBER_GZIP_SCOPE"):
        verify_member(raw, c, current_sha=sha(PDF))


@pytest.mark.parametrize("field,value", [
    ("filename", "https://other.invalid/foo"), ("offset", "-1"),
    ("length", "9000000"), ("timestamp", "20240931100000"), ("digest", "fake"),
])
def test_index_pointer_scope(field, value):
    row = entry()
    row[field] = value
    with pytest.raises(ValueError):
        parse_index(json.dumps(row).encode(), kind="hk", collection=COLLECTION)


def test_404_or_blank_is_not_proof_of_absence():
    for raw in (b"", b'{"message":"No Captures found"}'):
        with pytest.raises(ValueError):
            parse_index(raw, kind="hk", collection=COLLECTION)
