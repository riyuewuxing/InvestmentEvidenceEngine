"""Bounded fixed public CSI300 workbook/notice control.

Third-party archived original bytes are verified against immutable Git blob
identities. Neither Git author/committer timestamps nor current re-downloads
prove official historical first availability. Raw inputs are temporary only.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote

from .bounded_worker import run_json_worker, write_worker_result
from .historical_capture import SH
from .index_snapshot_scope import (
    git_blob_sha1,
    membership_difference,
    parse_csv,
    parse_notice,
    parse_rows,
    snapshot_summary,
)
from .official_pdf_transport import validate_pdf_shape

REPO = "riyuewuxing/InvestmentEvidenceEngine"
MAX_BYTES = 2*1024*1024
ARCHIVES = {
    "may": ("ad6429af8a17a4a2126578f3a463ef8aab864958", "20260506", "c1a707ffcb59e6477a9cc925e0a1f9f5777c3828", "621df91e10e63c6f330e8e7d7ed0cdcbd9417d57", "2026-05-06T04:34:35Z"),
    "jun": ("b7d9617d8139c0e25add2b1d83fec8e75c167a31", "20260616", "6ab2fb9d07129764c9a6c768b66162b4eca2883a", "900f28e5685094b78d308edbd3f61af3f51f9755", "2026-06-16T06:34:09Z"),
    "oct": ("bb7228ea92d7b6baee851f79dce6032b47ebd660", "20261020", "142d4f949516d69fddb83dcf7daeec5f05471845", "5e1a1489c43254f99fc9518a847b0ad8a36b9834", "2026-10-20T05:42:30Z"),
}
CSI_BASE = "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/"
NOTICE_URL = "https://oss-ch.csindex.com.cn/notice/20260529155822-" + quote("附件：部分指数样本调整名单.pdf")
KEYS = (*ARCHIVES, "notice", "current_members", "current_weights")


def routes(key: str) -> dict[str, str]:
    if key in ARCHIVES:
        ref, day, *_ = ARCHIVES[key]
        root = "https://raw.githubusercontent.com/shansb/cn-market-data-archive/" + ref + "/" + quote("00300-沪深300")
        return {"workbook": f"{root}/archive/{day}.xlsx", "csv": f"{root}/cons.csv"}
    if key == "notice":
        return {"pdf": NOTICE_URL}
    if key == "current_members":
        return {"workbook": CSI_BASE+"cons/000300cons.xls"}
    if key == "current_weights":
        return {"workbook": CSI_BASE+"closeweight/000300closeweight.xls"}
    raise ValueError("INDEX_FIXED_ROUTE")


def _get(url: str) -> dict:
    import httpx

    started = datetime.now(UTC)
    out = {"url": url, "started_at": started.isoformat()}
    deadline = time.monotonic()+12
    try:
        with httpx.Client(timeout=5.0, follow_redirects=False) as client:
            with client.stream("GET", url, headers={"Accept-Encoding": "identity",
                                                    "User-Agent": "Mozilla/5.0"}) as resp:
                out["http_status"] = resp.status_code
                if resp.status_code != 200 or str(resp.url) != url:
                    raise ValueError("INDEX_HTTP_SCOPE")
                if resp.headers.get("content-range") or resp.headers.get("content-encoding", "identity") not in {"", "identity"}:
                    raise ValueError("INDEX_HTTP_BODY_SCOPE")
                length = resp.headers.get("content-length")
                if length is not None and (not length.isdecimal() or int(length)>MAX_BYTES):
                    raise ValueError("INDEX_BODY_LENGTH")
                chunks = bytearray()
                for chunk in resp.iter_raw(chunk_size=65536):
                    if time.monotonic()>deadline or len(chunks)+len(chunk)>MAX_BYTES:
                        raise ValueError("INDEX_BODY_LIMIT")
                    chunks.extend(chunk)
                if not chunks or time.monotonic()>deadline or (length is not None and len(chunks)!=int(length)):
                    raise ValueError("INDEX_BODY_INCOMPLETE")
        raw = bytes(chunks)
        return out | {"retrieved_at": datetime.now(UTC).isoformat(),
                      "sha256": hashlib.sha256(raw).hexdigest(),
                      "body": base64.b64encode(raw).decode("ascii")}
    except Exception as exc:  # noqa: BLE001
        return out | {"error_type": type(exc).__name__}


def _child(key: str, path: Path) -> None:
    result = {name: _get(url) for name, url in routes(key).items()}
    write_worker_result(path, {"key": key, "files": result}, max_bytes=6*MAX_BYTES)


def workbook_rows(raw: bytes) -> list[list]:
    import xlrd

    # Archive extension is misleading. Accept only the observed legacy OLE Excel format.
    if not raw.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        raise ValueError("INDEX_WORKBOOK_NOT_OLE_XLS")
    book = xlrd.open_workbook(file_contents=raw, on_demand=True)
    try:
        if book.nsheets != 1:
            raise ValueError("INDEX_WORKBOOK_SHEET_SCOPE")
        sheet = book.sheet_by_index(0)
        if not 1 <= sheet.nrows <= 302 or not 9 <= sheet.ncols <= 12:
            raise ValueError("INDEX_WORKBOOK_SHAPE")
        rows = []
        for row in range(sheet.nrows):
            values = []
            for col in range(sheet.ncols):
                cell = sheet.cell(row, col)
                if cell.ctype == xlrd.XL_CELL_DATE:
                    values.append(xlrd.xldate_as_datetime(cell.value, book.datemode))
                elif cell.ctype == xlrd.XL_CELL_ERROR or cell.ctype == xlrd.XL_CELL_BOOLEAN:
                    raise ValueError("INDEX_WORKBOOK_CELL_TYPE")
                else:
                    values.append(cell.value)
            rows.append(values)
        return rows
    finally:
        book.release_resources()


def observe(key: str, directory: Path) -> tuple[dict, dict | None]:
    before = datetime.now(UTC)
    task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.public_csi300_snapshot_control", "--child", key),
                            timeout_seconds=30, max_bytes=6*MAX_BYTES)
    out = {"key": key, "status": "BLOCK", "worker_status": task.status,
           "elapsed_seconds": task.elapsed_seconds, "files": {}, "raw_body_retained": False}
    if task.status != "OK" or task.payload is None:
        return out, None
    try:
        payload = task.payload
        if payload["key"] != key or set(payload["files"]) != set(routes(key)):
            raise ValueError("INDEX_RECEIPT_SCOPE")
        bodies = {}
        for name, url in routes(key).items():
            item = payload["files"][name]
            meta = {k: v for k, v in item.items() if k != "body"}
            out["files"][name] = meta
            if item["url"] != url or "error_type" in item or item["http_status"] != 200:
                raise ValueError("INDEX_RECEIPT_HTTP")
            start = datetime.fromisoformat(item["started_at"])
            end = datetime.fromisoformat(item["retrieved_at"])
            if (start.utcoffset() is None or end.utcoffset() is None
                    or not before <= start <= end <= datetime.now(UTC)):
                raise ValueError("INDEX_RECEIPT_CLOCK")
            raw = base64.b64decode(item["body"], validate=True)
            if not 0 < len(raw) <= MAX_BYTES or hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise ValueError("INDEX_RECEIPT_HASH")
            target = directory/(key+"-"+name)
            with target.open("xb") as handle:
                handle.write(raw)
            raw2 = target.read_bytes()
            if raw2 != raw or hashlib.sha256(raw2).hexdigest() != item["sha256"]:
                raise ValueError("INDEX_REOPEN_HASH")
            meta |= {"bytes": len(raw), "parent_rehash": "MATCH", "temporary_rehash": "MATCH"}
            bodies[name] = raw2
        if key == "notice":
            from pypdf import PdfReader

            validate_pdf_shape(bodies["pdf"], max_bytes=MAX_BYTES)
            reader = PdfReader(io.BytesIO(bodies["pdf"]), strict=True)
            if reader.is_encrypted or not 1 <= len(reader.pages) <= 25:
                raise ValueError("INDEX_NOTICE_PAGES")
            notice = parse_notice(reader.pages[0].extract_text() or "")
            out |= {"status": "OBSERVED", "page_count": len(reader.pages), "notice": notice}
            return out, notice
        if key in ARCHIVES:
            ref, day, wb_sha, csv_sha, stamp = ARCHIVES[key]
            out |= {"archive_commit": ref, "archive_filename_day": day, "claimed_commit_time": stamp}
            for name, expected in (("workbook", wb_sha), ("csv", csv_sha)):
                observed = git_blob_sha1(bodies[name])
                out["files"][name]["git_blob_sha1"] = observed
                if observed != expected:
                    raise ValueError("INDEX_ARCHIVE_GIT_BLOB_MISMATCH")
            latest_label = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(SH).date()
        else:
            latest_label = datetime.fromisoformat(out["files"]["workbook"]["retrieved_at"]).astimezone(SH).date()
        rows = workbook_rows(bodies["workbook"])
        # Header/shape are diagnostics even if the source schema has changed.
        out["workbook_shape"] = [len(rows), len(rows[0])]
        out["workbook_header"] = [str(v)[:120] for v in rows[0]]
        snapshot = parse_rows(rows, weighted=key=="current_weights", latest_label=latest_label)
        if key in ARCHIVES:
            if parse_csv(bodies["csv"]) != snapshot["codes"]:
                raise ValueError("INDEX_ARCHIVE_CSV_WORKBOOK_MISMATCH")
            out["archive_csv_exact_order_match"] = True
        out |= {"status": "OBSERVED", "snapshot": snapshot_summary(snapshot)}
        return out, snapshot
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        out["error"] = msg if msg.startswith("INDEX_") and len(msg)<100 else type(exc).__name__
        return out, None


def run_control() -> dict:
    with TemporaryDirectory() as temp:
        # At most 3 bounded direct children at once; no retries.
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda key: observe(key, Path(temp)), KEYS))
    reports = {key: result[0] for key, result in zip(KEYS, results, strict=True)}
    parsed = {key: result[1] for key, result in zip(KEYS, results, strict=True)}
    out = {"status": "BLOCK", "observations": reports, "historical_availability_verified": False,
           "continuous_membership_verified": False, "listing_instance_identity_verified": False,
           "historical_weights_verified": False, "decision_authority": False,
           "execution_allowed": False, "research_only": True}
    if all(parsed[k] is not None for k in ("may", "jun", "notice")):
        delta = membership_difference(parsed["may"], parsed["jun"], notice=parsed["notice"])
        out["regular_rebalance"] = delta
        if delta["reviewed_notice_set_match"]:
            out["status"] = "WARN"
    if all(parsed[k] is not None for k in ("jun", "oct")):
        out["later_archive_change"] = membership_difference(parsed["jun"], parsed["oct"])
    if all(parsed[k] is not None for k in ("current_members", "current_weights")):
        a, b = parsed["current_members"], parsed["current_weights"]
        out["current_file_comparison"] = {
            "membership_label": a["label_day"], "weight_label": b["label_day"],
            "same_label_day": a["label_day"] == b["label_day"],
            "same_code_set": set(a["codes"]) == set(b["codes"]),
            "same_exchange_mapping": a["exchanges"] == b["exchanges"],
            "same_date_weight_membership_reconciled": a["label_day"] == b["label_day"]
            and a["exchanges"] == b["exchanges"],
        }
    return out


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    report = run_control() | {"executor_commit": os.environ["GITHUB_SHA"]}
    print("PUBLIC_CSI300_SNAPSHOT_CONTROL "+json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child" and sys.argv[2] in KEYS:
        _child(sys.argv[2], Path(sys.argv[3]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
