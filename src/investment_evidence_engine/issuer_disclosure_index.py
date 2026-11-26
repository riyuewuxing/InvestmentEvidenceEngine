"""Bounded observation of issuer disclosure metadata, not historical PIT proof."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .bounded_worker import run_json_worker, write_worker_result
from .evidence_time_guard import SHANGHAI
from .issuer_revision_control import DOCS, SUBJECT

DIRECTORY = "https://www.cninfo.com.cn/new/data/szse_stock.json"
QUERY = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
WINDOWS = (
    ("2025-04-27", "2025-04-30", ("annual_2024",)),
    ("2026-04-27", "2026-04-30", ("annual_2025", "policy_2026")),
    ("2026-08-27", "2026-08-30", ("half_2026",)),
)
MAX_BYTES = 4 * 1024 * 1024
PAGE_SIZE = 100


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def decode_object(raw: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("INDEX_ROOT_NOT_OBJECT")
    return value


def select_org(raw: bytes) -> str:
    rows = decode_object(raw).get("stockList")
    if not isinstance(rows, list):
        raise ValueError("DIRECTORY_SCHEMA")
    matches = [row for row in rows if isinstance(row, dict) and row.get("code") == SUBJECT]
    if len(matches) != 1:
        raise ValueError("DIRECTORY_SUBJECT_IDENTITY")
    org = matches[0].get("orgId")
    if not isinstance(org, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", org):
        raise ValueError("DIRECTORY_ORG_ID")
    return org


def parse_index(raw: bytes, org: str, window: tuple, observed_at: datetime) -> dict:
    start, end, targets = window
    body = decode_object(raw)
    rows = body.get("announcements")
    total = body.get("totalAnnouncement")
    if (type(total) is not int or not isinstance(rows, list)
            or not 0 <= total <= PAGE_SIZE or total != len(rows)):
        raise ValueError("INDEX_PAGE_COUNT_OR_COVERAGE")
    found = {}
    seen = set()
    expected = {DOCS[k][0].split("/")[-1].split(".")[0]: k for k in targets}
    for row in rows:
        if (not isinstance(row, dict) or row.get("secCode") != SUBJECT
                or row.get("orgId") != org):
            raise ValueError("INDEX_SUBJECT_MISMATCH")
        aid = row.get("announcementId")
        if type(aid) is int:
            aid = str(aid)
        if not isinstance(aid, str) or not re.fullmatch(r"[0-9]{1,30}", aid) or aid in seen:
            raise ValueError("INDEX_ANNOUNCEMENT_ID")
        seen.add(aid)
        if aid not in expected:
            continue
        kind = expected[aid]
        suffix, _, title = DOCS[kind]
        actual_title = row.get("announcementTitle")
        if not isinstance(actual_title, str) or title not in actual_title:
            raise ValueError("INDEX_TITLE_MISMATCH")
        url = row.get("adjunctUrl")
        if url != "finalpage/" + suffix:
            raise ValueError("INDEX_ATTACHMENT_MISMATCH")
        millis = row.get("announcementTime")
        if type(millis) is not int or not 0 < millis < 4_102_444_800_000:
            raise ValueError("INDEX_TIME_FIELD")
        stamp = datetime.fromtimestamp(millis / 1000, tz=UTC)
        local = stamp.astimezone(SHANGHAI)
        if not start <= local.date().isoformat() <= end or stamp > observed_at:
            raise ValueError("INDEX_TIME_SCOPE")
        found[kind] = {
            "announcement_id": aid, "attachment": url,
            "announcement_time_ms": millis, "platform_time_utc": stamp.isoformat(),
            "platform_time_shanghai": local.isoformat(),
            "platform_midnight": local.hour == local.minute == local.second == local.microsecond == 0,
            "path_day": suffix.split("/")[0],
            "first_availability_verified": False,
        }
    if set(found) != set(targets):
        raise ValueError("INDEX_TARGETS_MISSING")
    return {"returned_count": total, "target_records": found, "revision_universe_complete": False}


def _child(mode: str, org: str, path: Path) -> None:
    started = datetime.now(UTC)
    if mode == "directory":
        url, data = DIRECTORY, None
    else:
        start, end, _ = WINDOWS[int(mode)]
        url = QUERY
        data = urlencode({
            "pageNum": "1", "pageSize": str(PAGE_SIZE), "column": "szse",
            "tabName": "fulltext", "stock": SUBJECT + "," + org,
            "plate": "", "searchkey": "", "secid": "", "category": "", "trade": "",
            "seDate": start + "~" + end, "sortName": "", "sortType": "", "isHLtitle": "false",
        }).encode()
    request = Request(url, data=data, headers={
        "User-Agent": "Mozilla/5.0", "Accept": "application/json",
        "Accept-Encoding": "identity", "Referer": "https://www.cninfo.com.cn/",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    try:
        with build_opener(NoRedirect()).open(request, timeout=10) as response:
            if response.status != 200 or response.geturl() != url:
                raise ValueError("INDEX_HTTP_OR_URL")
            raw = response.read(MAX_BYTES + 1)
            if not 0 < len(raw) <= MAX_BYTES:
                raise ValueError("INDEX_BODY_SIZE")
    except Exception as exc:  # noqa: BLE001
        write_worker_result(path, {"mode": mode, "error": type(exc).__name__,
                                   "http_status": exc.code if isinstance(exc, HTTPError) else None})
        return
    write_worker_result(path, {
        "mode": mode, "url": url, "body": base64.b64encode(raw).decode("ascii"),
        "sha256": hashlib.sha256(raw).hexdigest(), "started_at": started.isoformat(),
        "retrieved_at": datetime.now(UTC).isoformat(),
    })


def observe(mode: str, org: str) -> tuple[dict, str]:
    out = {"mode": mode, "status": "BLOCK", "decision_authority": False}
    task = run_json_worker((sys.executable, "-m",
                            "investment_evidence_engine.issuer_disclosure_index",
                            "--child", mode, org), timeout_seconds=25, max_bytes=6 * 1024 * 1024)
    out |= {"worker_status": task.status, "elapsed_seconds": task.elapsed_seconds}
    if task.status != "OK" or task.payload is None:
        return out, org
    try:
        p = task.payload
        if p.get("mode") != mode:
            raise ValueError("INDEX_RECEIPT_MODE")
        if p.get("error"):
            return out | {"error": p["error"], "http_status": p.get("http_status")}, org
        if p["url"] != (DIRECTORY if mode == "directory" else QUERY):
            raise ValueError("INDEX_RECEIPT_URL")
        start = datetime.fromisoformat(p["started_at"])
        end = datetime.fromisoformat(p["retrieved_at"])
        if start.utcoffset() is None or end.utcoffset() is None or not start <= end <= datetime.now(UTC):
            raise ValueError("INDEX_RECEIPT_TIME")
        raw = base64.b64decode(p["body"], validate=True)
        if not 0 < len(raw) <= MAX_BYTES or hashlib.sha256(raw).hexdigest() != p["sha256"]:
            raise ValueError("INDEX_BODY_HASH")
        out |= {"sha256": p["sha256"], "bytes": len(raw), "parent_rehash": "MATCH",
                "retrieved_at": end.isoformat(), "raw_body_retained": False}
        if mode == "directory":
            org = select_org(raw)
            out["org_id"] = org
        else:
            out |= parse_index(raw, org, WINDOWS[int(mode)], end)
    except Exception as exc:  # noqa: BLE001
        code = str(exc)
        return out | {"error": code if re.fullmatch(r"(?:INDEX|DIRECTORY|DUPLICATE)_[A-Z0-9_]+", code)
                      else type(exc).__name__}, org
    return out | {"status": "OBSERVED"}, org


def run_control() -> dict:
    first, org = observe("directory", "")
    observations = [first]
    if first["status"] == "OBSERVED":
        for index in range(len(WINDOWS)):
            item, _ = observe(str(index), org)
            observations.append(item)
            if item["status"] != "OBSERVED":
                break
    success = len(observations) == 4 and all(row["status"] == "OBSERVED" for row in observations)
    return {"status": "WARN" if success else "BLOCK", "observations": observations,
            "historical_availability_verified": False, "pit_safe": False,
            "decision_authority": False, "raw_body_retained": False}


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] != "--child":
        raise SystemExit(2)
    _child(sys.argv[2], sys.argv[3], Path(sys.argv[4]))
