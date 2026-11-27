"""One bounded historical archive search, not a first-publication claim.

CDX metadata is distinct from a successful exact replay and payload match.
No raw document redistribution, no automatic network retry, no decision admission.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode

from .bounded_worker import run_json_worker, write_worker_result
from .official_pdf_transport import read_bounded_pdf
from .snapshot_integrity import strict_json_loads

REPO = "riyuewuxing/InvestmentEvidenceEngine"
MODULE = "investment_evidence_engine.historical_archive_probe"
CDX = "https://web.archive.org/cdx/search/cdx"
TARGETS = {
    "hk": ("https://www1.hkexnews.hk/listedco/listconews/sehk/2024/0828/2024082800846.pdf",
           "26a35387d756dc436ac9dc536f92af3cf2359ab8df47fc20459f2d7058aeb0de"),
    "cninfo": ("https://static.cninfo.com.cn/finalpage/2024-08-29/1221030553.PDF",
               "efa9b512e85b259c85c481c6d6a49e450a2f9e739886fd5255da136841986216"),
}
START = "20240828"
END = "20241231"
FIELDS = ["timestamp", "original", "mimetype", "statuscode", "digest"]
LIMIT = 21
MAX_INDEX_BYTES = 128 * 1024


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse_cdx(raw: bytes, original: str) -> dict:
    if not raw.strip():
        raise ValueError("CDX_EMPTY_UNINTERPRETABLE")
    value = strict_json_loads(raw)
    if value == []:
        return {"status": "NO_CAPTURE_RETURNED", "rows": 0}
    if (not isinstance(value, list) or not value or value[0] != FIELDS
            or len(value) - 1 >= LIMIT):
        raise ValueError("CDX_SCHEMA_OR_CAP")
    rows = value[1:]
    eligible = []
    seen = set()
    for row in rows:
        if (not isinstance(row, list) or len(row) != len(FIELDS)
                or not all(isinstance(v, str) for v in row)):
            raise ValueError("CDX_ROW")
        stamp, url, mime, status, digest = row
        if not re.fullmatch(r"[0-9]{14}", stamp) or not START <= stamp[:8] <= END:
            raise ValueError("CDX_TIMESTAMP_SCOPE")
        datetime.strptime(stamp, "%Y%m%d%H%M%S")
        if stamp in seen:
            raise ValueError("CDX_DUPLICATE_CAPTURE_TIME")
        seen.add(stamp)
        if url != original or mime != "application/pdf" or status != "200":
            continue
        if not re.fullmatch(r"[A-Z2-7]{32}", digest):
            continue
        eligible.append({"capture_stamp": stamp, "original": url, "digest_sha1_base32": digest})
    return {"status": "CANDIDATE" if eligible else "NO_EXACT_PDF_CAPTURE_RETURNED",
            "rows": len(rows), "eligible_count": len(eligible),
            "candidate": min(eligible, key=lambda row: row["capture_stamp"]) if eligible else None}


def verify_replay(raw: bytes, candidate: dict, memento: str | None, current_sha: str) -> dict:
    captured = datetime.strptime(candidate["capture_stamp"], "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    if not memento or parsedate_to_datetime(memento) != captured:
        raise ValueError("MEMENTO_CAPTURE_TIME_UNVERIFIED")
    digest = base64.b32encode(hashlib.sha1(raw).digest()).decode("ascii")
    if digest != candidate["digest_sha1_base32"]:
        raise ValueError("ARCHIVE_PAYLOAD_DIGEST_MISMATCH")
    observed = sha256(raw)
    return {"capture_at": captured.isoformat(), "archive_payload_sha256": observed,
            "archive_digest_match": True, "current_bytes_match": observed == current_sha,
            "bytes": len(raw), "archive_capture_witness_only": True,
            "first_publication_verified": False, "pit_safe": False}


def child(kind: str, target: Path, result: Path) -> None:
    import httpx

    original, current_sha = TARGETS[kind]
    params = urlencode({"url": original, "matchType": "exact", "from": START,
                        "to": END, "output": "json", "fl": ",".join(FIELDS),
                        "limit": str(LIMIT)})
    index_url = CDX + "?" + params
    out = {"kind": kind, "status": "BLOCK", "original": original,
           "index_url": index_url, "started_at": datetime.now(UTC).isoformat()}
    try:
        with httpx.Client(timeout=httpx.Timeout(10), follow_redirects=False) as client:
            with client.stream("GET", index_url, headers={"Accept-Encoding": "identity"}) as response:
                out["http_status"] = response.status_code
                if (response.status_code != 200 or str(response.url) != index_url
                        or response.headers.get("Content-Range")
                        or response.headers.get("Content-Encoding", "identity").lower() not in ("", "identity")):
                    raise ValueError("CDX_HTTP_SCOPE")
                raw = bytearray()
                deadline = time.monotonic() + 10
                for chunk in response.iter_raw():
                    if time.monotonic() > deadline or len(raw) + len(chunk) > MAX_INDEX_BYTES:
                        raise ValueError("CDX_BODY_BOUND")
                    raw.extend(chunk)
                length = response.headers.get("Content-Length")
                if length is not None and int(length) != len(raw):
                    raise ValueError("CDX_LENGTH")
            body = bytes(raw)
            out.update(index_sha256=sha256(body), index_bytes=len(body),
                       index_observed_at=datetime.now(UTC).isoformat())
            (target / "index").write_bytes(body)
            parsed = parse_cdx(body, original)
            out["index"] = parsed
            if parsed["status"] != "CANDIDATE":
                out["status"] = parsed["status"]
            else:
                candidate = parsed["candidate"]
                replay = "https://web.archive.org/web/" + candidate["capture_stamp"] + "id_/" + original
                out["replay_url"] = replay
                with client.stream("GET", replay, headers={"Accept-Encoding": "identity"}) as response:
                    out["replay_http_status"] = response.status_code
                    if str(response.url) != replay:
                        raise ValueError("ARCHIVE_REPLAY_ROUTE")
                    pdf = read_bounded_pdf(response, time.monotonic() + 15)
                    memento = response.headers.get("Memento-Datetime")
                (target / "pdf").write_bytes(pdf)
                out["replay_observed_sha256"] = sha256(pdf)
                out["replay_observed_at"] = datetime.now(UTC).isoformat()
                out["capture"] = verify_replay(pdf, candidate, memento, current_sha)
                out["status"] = "CAPTURE_WITNESSED" if out["capture"]["current_bytes_match"] else "DIFFERENT_ARCHIVE_BYTES"
    except Exception as exc:
        out["error_type"] = type(exc).__name__
        if type(exc) is ValueError:
            out["error"] = str(exc)[:120]
    write_worker_result(result, out)


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    observations = []
    for kind in TARGETS:
        with TemporaryDirectory() as folder:
            target = Path(folder)
            task = run_json_worker((sys.executable, "-m", MODULE, "--child", kind, folder),
                                   timeout_seconds=45, max_bytes=65536)
            out = task.payload or {"kind": kind, "status": "BLOCK"}
            out.update(worker_status=task.status, elapsed_seconds=task.elapsed_seconds)
            for name, field in (("index", "index_sha256"), ("pdf", "replay_observed_sha256")):
                if field in out:
                    match = (target / name).is_file() and sha256((target / name).read_bytes()) == out[field]
                    out[name + "_parent_rehash"] = "MATCH" if match else "NOT_VERIFIED"
                    if not match:
                        out["status"] = "BLOCK"
            observations.append(out)
        # Shared archive access blocked: do not retry or bypass its restriction.
        if out.get("http_status") in (401, 403, 429) or task.status != "OK" or out.get("error_type") in {"ConnectTimeout", "ReadTimeout", "ConnectError"}:
            break
    report = {"executor_commit": os.environ["GITHUB_SHA"], "observations": observations,
              "archive_capture_witness_count": sum(v["status"] == "CAPTURE_WITNESSED" for v in observations),
              "first_publication_verified": False, "historical_universe_verified": False,
              "raw_source_retained": False, "pit_safe": False, "decision_authority": False,
              "execution_allowed": False, "status": "WARN" if any(v["status"] == "CAPTURE_WITNESSED" for v in observations) else "BLOCK"}
    print("PUBLIC_HISTORICAL_ARCHIVE " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--child" and sys.argv[2] in TARGETS:
        child(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
