"""Bounded official BSE code-transition observation, not an active universe or PIT vintage."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from .bounded_worker import run_json_worker, write_worker_result
from .issuer_disclosure_index import NoRedirect

URLS = {
    "mapping": "https://www.bse.cn/code_mapping/200025792.html",
    "pilot_names": "https://www.bse.cn/important_news/200025487.html",
    "pilot_effective": "https://www.bse.cn/important_news/200025603.html",
    "bulk_effective": "https://www.bse.cn/important_news/200026735.html",
}
MAX_BYTES = 1024 * 1024
PILOT_DAY = date(2025, 5, 6)
BULK_DAY = date(2025, 10, 9)
PILOTS = {
    "833819": ("920819", "颖泰生物"),
    "830799": ("920799", "艾融软件"),
    "831445": ("920445", "龙竹科技"),
    "430489": ("920489", "佳先股份"),
    "839167": ("920167", "同享科技"),
    "834682": ("920682", "球冠电缆"),
}


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.rows = []
        self.hidden = 0
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if self.hidden:
            return
        if tag == "tr":
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
            return
        if self.hidden:
            return
        if tag in {"td", "th"} and self.cell is not None and self.row is not None:
            self.row.append("".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
            self.cell = None

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)
            if self.cell is not None:
                self.cell.append(data)


def parse_page(raw: bytes, charset: str) -> Page:
    if charset.lower() not in {"utf-8", "gb18030", "gbk", "gb2312"}:
        raise ValueError("BSE_CHARSET")
    if not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("BSE_BODY_SIZE")
    page = Page()
    page.feed(raw.decode(charset, errors="strict"))
    page.close()
    return page


def mapping_fields(page: Page) -> dict:
    text = "".join("".join(page.parts).split())
    if "新旧代码对照表" not in text or "原精选层的挂牌日期" not in text:
        raise ValueError("BSE_MAPPING_IDENTITY")
    headers = ["序号", "证券简称", "上市日期", "旧代码", "新代码"]
    starts = [i for i, row in enumerate(page.rows) if row == headers]
    if len(starts) != 1:
        raise ValueError("BSE_MAPPING_HEADER")
    rows = []
    for row in page.rows[starts[0] + 1:]:
        if len(row) != 5 or not re.fullmatch(r"[0-9]+", row[0]):
            break
        i, name, listed, old, new = row
        if (int(i) != len(rows) + 1 or not name or
                not re.fullmatch(r"(?:4|8)[0-9]{5}", old) or
                not re.fullmatch(r"920[0-9]{3}", new)):
            raise ValueError("BSE_MAPPING_ROW")
        day = date.fromisoformat("-".join(
            [listed.split("/")[0], *[v.zfill(2) for v in listed.split("/")[1:]]]))
        rows.append((name, day.isoformat(), old, new))
    if len(rows) != 248 or any(len({row[i] for row in rows}) != len(rows) for i in (2, 3)):
        raise ValueError("BSE_MAPPING_COUNT_OR_DUPLICATE")
    old_to_row = {r[2]: r for r in rows}
    for old, (new, name) in PILOTS.items():
        if old not in old_to_row or (old_to_row[old][3], old_to_row[old][0]) != (new, name):
            raise ValueError("BSE_PILOT_IDENTITY_MISMATCH")
    differing = [r for r in rows if r[2][-3:] != r[3][-3:]]
    example = old_to_row.get("837023")
    if not example or example[3] != "920123" or not differing:
        raise ValueError("BSE_SUFFIX_COUNTEREXAMPLE")
    return {
        "mapped_legacy_security_count": len(rows),
        "pilot_count": len(PILOTS),
        "other_mapped_count": len(rows) - len(PILOTS),
        "different_last_three_digit_count": len(differing),
        "selected_layer_date_before_bse_open_count": sum(r[1] < "2021-11-15" for r in rows),
        "mapping_sha256": hashlib.sha256(json.dumps(rows, ensure_ascii=False,
                                                   separators=(",", ":")).encode()).hexdigest(),
        "pilot_pairs": [{"old": k, "new": v[0]} for k, v in sorted(PILOTS.items())],
        "suffix_counterexample": {"old": example[2], "new": example[3]},
        "table_list_date_not_uniform_bse_listing_date": True,
        "active_listing_verified": False,
    }


def notice_fields(kind: str, page: Page) -> dict:
    text = "".join("".join(page.parts).split())
    markers = {
        "pilot_names": ("2025年4月11日", "存量上市公司代码切换试点股票名单",
                        "6只股票进行试点切换", *(name for _, name in PILOTS.values())),
        "pilot_effective": ("2025年4月25日", "存量上市公司代码切换试点上线",
                            "自2025年5月6日起", "其他242只存量上市公司股票"),
        "bulk_effective": ("2025年9月12日", "存量上市公司代码切换上线",
                           "自2025年10月9日起", "存量股票启用新证券代码"),
    }
    if kind not in markers or not all(x in text for x in markers[kind]):
        raise ValueError("BSE_NOTICE_FIELDS")
    return {"declared_document_day": {"pilot_names": "2025-04-11",
                                     "pilot_effective": "2025-04-25",
                                     "bulk_effective": "2025-09-12"}[kind],
            "declared_effective_day": {"pilot_names": None, "pilot_effective": PILOT_DAY.isoformat(),
                                       "bulk_effective": BULK_DAY.isoformat()}[kind],
            "historical_first_availability_verified": False}


def _child(kind: str, path: Path) -> None:
    url = URLS[kind]
    started = datetime.now(UTC)
    req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"})
    try:
        with build_opener(NoRedirect()).open(req, timeout=12) as response:
            if response.status != 200 or response.geturl() != url:
                raise ValueError("BSE_RESPONSE_SCOPE")
            if response.headers.get("Content-Encoding", "identity").lower() not in {"", "identity"}:
                raise ValueError("BSE_ENCODING")
            if response.headers.get("Content-Range") is not None:
                raise ValueError("BSE_PARTIAL_RESPONSE")
            raw = response.read(MAX_BYTES + 1)
            charset = response.headers.get_content_charset() or "utf-8"
            declared = response.headers.get("Content-Length")
            if not 0 < len(raw) <= MAX_BYTES or (declared is not None and int(declared) != len(raw)):
                raise ValueError("BSE_BODY_SIZE")
    except Exception as exc:  # noqa: BLE001
        write_worker_result(path, {"kind": kind, "error": type(exc).__name__,
                                   "http_status": exc.code if isinstance(exc, HTTPError) else None})
        return
    write_worker_result(path, {"kind": kind, "url": url, "charset": charset,
                               "started_at": started.isoformat(),
                               "retrieved_at": datetime.now(UTC).isoformat(),
                               "sha256": hashlib.sha256(raw).hexdigest(),
                               "body": base64.b64encode(raw).decode("ascii")})


def observe(kind: str) -> dict:
    task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.bse_code_transition_control",
                            "--child", kind), timeout_seconds=20, max_bytes=2 * MAX_BYTES)
    out = {"kind": kind, "url": URLS[kind], "status": "BLOCK",
           "worker_status": task.status, "elapsed_seconds": task.elapsed_seconds}
    if task.status != "OK" or task.payload is None:
        return out
    try:
        p = task.payload
        if p.get("kind") != kind:
            raise ValueError("BSE_RECEIPT_KIND")
        if p.get("error"):
            return out | {"error": p["error"], "http_status": p.get("http_status")}
        begin, end = datetime.fromisoformat(p["started_at"]), datetime.fromisoformat(p["retrieved_at"])
        if (p["url"] != URLS[kind] or begin.utcoffset() is None or end.utcoffset() is None
                or not begin <= end <= datetime.now(UTC)):
            raise ValueError("BSE_RECEIPT_SCOPE")
        raw = base64.b64decode(p["body"], validate=True)
        digest = hashlib.sha256(raw).hexdigest()
        if not 0 < len(raw) <= MAX_BYTES or digest != p["sha256"]:
            raise ValueError("BSE_RECEIPT_HASH")
        out |= {"sha256": digest, "bytes": len(raw), "retrieved_at": end.isoformat(),
                "parent_rehash": "MATCH", "raw_body_retained": False}
        page = parse_page(raw, p["charset"])
        fields = mapping_fields(page) if kind == "mapping" else notice_fields(kind, page)
        return out | {"status": "OBSERVED", "fields": fields}
    except Exception as exc:  # noqa: BLE001
        code = str(exc)
        return out | {"error": code if re.fullmatch(r"BSE_[A-Z_]+", code) else type(exc).__name__}


def main() -> int:
    if os.environ["GITHUB_REPOSITORY"] != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    receipts = [observe(kind) for kind in URLS]
    status = "WARN" if all(r["status"] == "OBSERVED" for r in receipts) else "BLOCK"
    report = {"status": status, "sources": receipts, "executor_commit": os.environ["GITHUB_SHA"],
              "scope": "LEGACY_CODE_TRANSITIONS_NOT_CURRENT_ACTIVE_BSE_LIST",
              "historical_first_availability_verified": False, "active_listing_verified": False,
              "pit_safe": False, "decision_authority": False, "execution_allowed": False}
    print("PUBLIC_BSE_CODE_TRANSITION " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if status == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child" and sys.argv[2] in URLS:
        _child(sys.argv[2], Path(sys.argv[3]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
