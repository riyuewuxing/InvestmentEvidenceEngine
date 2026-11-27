"""Bounded historical Common Crawl index and exact WARC payload witness.

Fixed independent archive route for two already identified issuer PDFs.
No access-denial retries, historical first-publication claim, or raw redistribution.
Reference: https://www.commoncrawl.org/cdxj-index and /get-started.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import zlib
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from .bounded_worker import run_json_worker, write_worker_result
from .historical_archive_probe import TARGETS
from .issuer_disclosure_index import NoRedirect
from .snapshot_integrity import strict_json_loads
from .sources import read_official_body

REPO = "riyuewuxing/InvestmentEvidenceEngine"
COLLECTIONS = {"CC-MAIN-2024-38": ("20240907", "20240921"),
               "CC-MAIN-2024-42": ("20241003", "20241016")}
INDEX = "https://index.commoncrawl.org/"
DATA = "https://data.commoncrawl.org/"
MAX_INDEX = 128 * 1024
MAX_MEMBER = 8 * 1024 * 1024
MAX_EXPANDED = 16 * 1024 * 1024
MAX_ROWS = 20
UA = "InvestmentEvidenceEngine/0.1 (+https://github.com/riyuewuxing/InvestmentEvidenceEngine)"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def digest32(raw: bytes) -> str:
    return base64.b32encode(hashlib.sha1(raw).digest()).decode("ascii")


def index_url(kind: str, collection: str) -> str:
    original, _ = TARGETS[kind]
    if collection not in COLLECTIONS:
        raise ValueError("CC_COLLECTION_SCOPE")
    return INDEX + collection + "-index?" + urlencode({
        "url": original, "matchType": "exact", "output": "json"})


def parse_index(raw: bytes, *, kind: str, collection: str) -> dict:
    """Do not treat a missing, partial, or capped response as proven absence."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_INDEX:
        raise ValueError("CC_INDEX_BODY")
    start, end = COLLECTIONS[collection]
    original, _ = TARGETS[kind]
    lines = raw.splitlines()
    if not 0 < len(lines) <= MAX_ROWS or any(not line.strip() for line in lines):
        raise ValueError("CC_INDEX_COUNT")
    eligible, seen = [], set()
    for line in lines:
        row = strict_json_loads(line)
        if not isinstance(row, dict):
            raise ValueError("CC_INDEX_ROW")
        stamp, url = row.get("timestamp"), row.get("url")
        if (not isinstance(stamp, str) or not re.fullmatch(r"[0-9]{14}", stamp)
                or not start <= stamp[:8] <= end or not isinstance(url, str)):
            raise ValueError("CC_INDEX_SCOPE")
        datetime.strptime(stamp, "%Y%m%d%H%M%S")
        if row.get("status") != "200" or url != original:
            continue
        if row.get("mime") != "application/pdf" or row.get("mime-detected", "application/pdf") != "application/pdf":
            continue
        dg, fn, offset, length = (row.get(k) for k in ("digest", "filename", "offset", "length"))
        if (not isinstance(dg, str) or not re.fullmatch(r"[A-Z2-7]{32}", dg)
                or not isinstance(fn, str) or not re.fullmatch(
                    r"crawl-data/" + re.escape(collection) + r"/segments/[0-9]+\.[0-9]+/warc/[A-Za-z0-9_-]+\.warc\.gz", fn)
                or not isinstance(offset, str) or not re.fullmatch(r"[0-9]{1,13}", offset)
                or not isinstance(length, str) or not re.fullmatch(r"[0-9]{1,8}", length)
                or not 0 < int(length) <= MAX_MEMBER):
            raise ValueError("CC_INDEX_POINTER")
        locator = (fn, int(offset), int(length))
        if locator in seen:
            raise ValueError("CC_INDEX_DUPLICATE")
        seen.add(locator)
        eligible.append({"timestamp": stamp, "url": url, "digest": dg, "filename": fn,
                         "offset": int(offset), "length": int(length)})
    eligible.sort(key=lambda x: (x["timestamp"], x["filename"], x["offset"]))
    return {"rows": len(lines), "eligible_count": len(eligible),
            "status": "CANDIDATE" if eligible else "NO_EXACT_PDF_ROW_RETURNED",
            "candidate": eligible[0] if eligible else None}


def _headers(raw: bytes) -> tuple[str, dict[str, str], bytes]:
    header, sep, body = raw.partition(b"\r\n\r\n")
    if not sep or not 0 < len(header) <= 32 * 1024:
        raise ValueError("CC_HEADER_BOUND")
    lines = header.decode("iso-8859-1").split("\r\n")
    fields = {}
    for line in lines[1:]:
        key, colon, value = line.partition(":")
        k = key.lower()
        if (not colon or not re.fullmatch(r"[A-Za-z0-9-]+", key) or k in fields
                or not value.strip() or "\x00" in value):
            raise ValueError("CC_HEADER_SCHEMA")
        fields[k] = value.strip()
    return lines[0], fields, body


def verify_member(member: bytes, candidate: dict, *, current_sha: str) -> tuple[dict, bytes]:
    """Exact single gzip member, WARC/HTTP identity, lengths and both digests."""
    if not 0 < len(member) == candidate["length"] <= MAX_MEMBER:
        raise ValueError("CC_MEMBER_LENGTH")
    try:
        dec = zlib.decompressobj(16 + zlib.MAX_WBITS)
        raw = dec.decompress(member, MAX_EXPANDED + 1)
    except zlib.error as exc:
        raise ValueError("CC_MEMBER_GZIP") from exc
    if (len(raw) > MAX_EXPANDED or not dec.eof or dec.unused_data or dec.unconsumed_tail):
        raise ValueError("CC_MEMBER_GZIP_SCOPE")
    version, warc, body = _headers(raw)
    cap = datetime.strptime(candidate["timestamp"], "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    if (version not in {"WARC/1.0", "WARC/1.1"} or warc.get("warc-type") != "response"
            or warc.get("warc-target-uri") != candidate["url"]
            or warc.get("warc-date") != cap.strftime("%Y-%m-%dT%H:%M:%SZ")
            or warc.get("warc-truncated") is not None
            or warc.get("content-type", "").lower().replace(" ", "") != "application/http;msgtype=response"):
        raise ValueError("CC_WARC_IDENTITY")
    size = warc.get("content-length", "")
    if not size.isdecimal() or len(body) != int(size) + 4 or body[-4:] != b"\r\n\r\n":
        raise ValueError("CC_WARC_BLOCK_LENGTH")
    block = body[:-4]
    if warc.get("warc-block-digest") != "sha1:" + digest32(block):
        raise ValueError("CC_WARC_BLOCK_DIGEST")
    status, headers, pdf = _headers(block)
    if (not re.fullmatch(r"HTTP/1\.[01] 200(?: .*)?", status)
            or headers.get("content-type", "").split(";")[0].strip().lower() != "application/pdf"
            or headers.get("content-encoding", "identity").lower() != "identity"
            or "transfer-encoding" in headers or "content-range" in headers
            or ("content-length" in headers and headers["content-length"] != str(len(pdf)))):
        raise ValueError("CC_ARCHIVED_HTTP_SCOPE")
    if not pdf.startswith(b"%PDF-") or b"%%EOF" not in pdf[-1024:]:
        raise ValueError("CC_PDF_SCOPE")
    expected = candidate["digest"]
    if digest32(pdf) != expected or warc.get("warc-payload-digest") != "sha1:" + expected:
        raise ValueError("CC_WARC_PAYLOAD_DIGEST")
    observed = sha(pdf)
    return {"capture_at": cap.isoformat(), "archive_payload_sha256": observed,
            "archive_payload_bytes": len(pdf), "index_and_warc_payload_digest_match": True,
            "warc_block_digest_match": True, "current_bytes_match": observed == current_sha,
            "archive_capture_witness_only": True, "first_publication_verified": False,
            "pit_safe": False, "decision_authority": False}, pdf


def _child(kind: str, collection: str, target: Path, result: Path) -> None:
    url = index_url(kind, collection)
    out = {"kind": kind, "collection": collection, "index_url": url, "status": "BLOCK",
           "started_at": datetime.now(UTC).isoformat()}
    opener = build_opener(NoRedirect())
    try:
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
            with opener.open(req, timeout=10) as response:
                out["http_status"] = response.status
                if response.geturl() != url:
                    raise ValueError("CC_INDEX_REDIRECT")
                raw = read_official_body(response, limit=MAX_INDEX)
        except HTTPError as exc:
            out["http_status"] = exc.code
            # 404 is not proof of absence: only preserve the observed response.
            if exc.code == 404:
                out["status"] = "HTTP_404_NO_ROW_CONFIRMED"
            else:
                out["error_type"] = type(exc).__name__
            write_worker_result(result, out)
            return
        (target / "index").write_bytes(raw)
        out.update(index_sha256=sha(raw), index_bytes=len(raw))
        report = parse_index(raw, kind=kind, collection=collection)
        out["index"] = report
        out["status"] = report["status"]
        if report["status"] == "CANDIDATE":
            candidate = report["candidate"]
            first, size = candidate["offset"], candidate["length"]
            end = first + size - 1
            archive_url = DATA + candidate["filename"]
            req = Request(archive_url, headers={"User-Agent": UA, "Accept-Encoding": "identity",
                                                "Range": f"bytes={first}-{end}"})
            with opener.open(req, timeout=15) as response:
                out["archive_http_status"] = response.status
                if (response.status != 206 or response.geturl() != archive_url
                        or not re.fullmatch(rf"bytes {first}-{end}/[0-9]+",
                                            response.headers.get("Content-Range", ""))
                        or response.headers.get("Content-Encoding", "identity").lower() != "identity"
                        or response.headers.get("Content-Length") != str(size)):
                    raise ValueError("CC_RANGE_SCOPE")
                member = response.read(size + 1)
            (target / "member").write_bytes(member)
            out["member_sha256"] = sha(member)
            verified, pdf = verify_member(member, candidate, current_sha=TARGETS[kind][1])
            (target / "pdf").write_bytes(pdf)
            out["capture"] = verified
            out["status"] = "CAPTURE_WITNESSED" if verified["current_bytes_match"] else "DIFFERENT_ARCHIVE_BYTES"
    except Exception as exc:  # noqa: BLE001
        out["status"] = "BLOCK"
        out["error_type"] = type(exc).__name__
        if isinstance(exc, HTTPError):
            out["archive_http_status"] = exc.code
        if type(exc) is ValueError and str(exc).startswith("CC_"):
            out["error"] = str(exc)
    out["finished_at"] = datetime.now(UTC).isoformat()
    write_worker_result(result, out)


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    observations = []
    stop = False
    for kind in TARGETS:
        for collection in COLLECTIONS:
            with TemporaryDirectory() as temp:
                target = Path(temp)
                task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.common_crawl_witness",
                                        "--child", kind, collection, temp),
                                       timeout_seconds=40, max_bytes=64 * 1024)
                out = task.payload or {"kind": kind, "collection": collection, "status": "BLOCK"}
                out.update(worker_status=task.status, elapsed_seconds=task.elapsed_seconds)
                for name, digest in (("index", out.get("index_sha256")), ("member", out.get("member_sha256")),
                                     ("pdf", out.get("capture", {}).get("archive_payload_sha256"))):
                    if digest is not None:
                        match = (target / name).is_file() and sha((target / name).read_bytes()) == digest
                        out[name + "_parent_rehash"] = "MATCH" if match else "NOT_VERIFIED"
                        if not match:
                            out["status"] = "BLOCK"
                observations.append(out)
            # Never retry access denials, rate limits, transport or schema failures.
            if out["status"] == "BLOCK" or task.status != "OK":
                stop = True
                break
            if out["status"] == "CAPTURE_WITNESSED":
                break
        if stop:
            break
    count = sum(row["status"] == "CAPTURE_WITNESSED" for row in observations)
    report = {"executor_commit": os.environ["GITHUB_SHA"], "observations": observations,
              "capture_witness_count": count, "historical_first_availability_verified": False,
              "raw_bodies_retained": False, "pit_safe": False, "decision_authority": False,
              "status": "WARN" if count else "BLOCK"}
    print("PUBLIC_COMMON_CRAWL_WITNESS " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if count else 2


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "--child":
        _child(sys.argv[2], sys.argv[3], Path(sys.argv[4]), Path(sys.argv[5]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
