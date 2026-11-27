"""Fixed external counterparty/issuer procurement chronology; no formal admission.

Only derived fields and byte receipts leave ephemeral worker memory. Government
award, issuer-reported agreement and actual payments are different claims.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import httpx
from pypdf import PdfReader

from .bounded_worker import run_json_worker, write_worker_result
from .official_pdf_transport import retrieve_pdf_bytes, validate_pdf_shape
from .public_symbol_change_control import compact

REPO = "riyuewuxing/InvestmentEvidenceEngine"
LIMIT = 2 * 1024 * 1024
URLS = {
    "tender": "https://www.ccgp-shaanxi.gov.cn/freecms/site/shaanxi/ggxx/info/2026/8a69c6f19b961dc6019c025e897a7ee4.html",
    "award": "https://www.ccgp-shaanxi.gov.cn/freecms/site/shaanxi/ggxx/info/2026/8a69c25d9c309202019c9945a2b97c60.html",
    "issuer_award": "https://static.cninfo.com.cn/finalpage/2026-03-12/1225004714.PDF",
    "issuer_agreement": "https://static.cninfo.com.cn/finalpage/2026-03-27/1225034259.PDF",
}
PROJECT = "ZXGJ-YLZB-2026(3)"
MEMBER = "江苏楹环城市环境服务有限公司"
LEAD = "西安市阎良区天盛建设工程有限公司"
BUYER = "西安市阎良区城市管理和综合执法局"
TOTAL = 98_928_000
ANNUAL = 32_976_000


class VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "template"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "template"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def require(text: str, *anchors: str) -> None:
    if not all(compact(a) in text for a in anchors):
        raise ValueError("PROCUREMENT_REVIEWED_ANCHORS")


def parse_government(key: str, html: str) -> dict:
    parser = VisibleText()
    parser.feed(html)
    text = compact(" ".join(parser.parts))
    require(text, PROJECT, BUYER, "阎良区城区环卫作业市场化服务项目")
    if key == "tender":
        require(text, "2026-01-2911:06:04", "100,488,500.00元", "本合同包接受联合体投标")
        return {"stage": "TENDER", "project_id": PROJECT, "publisher_time_label": "2026-01-29 11:06:04",
                "budget_cny": 100_488_500, "consortium_allowed": True}
    if key != "award":
        raise ValueError("PROCUREMENT_SCOPE")
    require(text, "2026-02-2711:29:48", "中标(成交)结果公告",
            LEAD + "(联合体成员:" + MEMBER + ")", "98,928,000.00", "三年",
            "78条道路", "公共厕所56座", "1座生活垃圾压缩站")
    return {"stage": "AWARD", "project_id": PROJECT, "publisher_time_label": "2026-02-27 11:29:48",
            "buyer": BUYER, "lead": LEAD, "member": MEMBER, "consortium_total_cny": TOTAL,
            "term_years": 3, "source_role": "PROCUREMENT_AGENT_PUBLICATION"}


def parse_issuer(key: str, pages: tuple[str, ...]) -> dict:
    if not 1 <= len(pages) <= 4:
        raise ValueError("PROCUREMENT_PAGE_SCOPE")
    first, full = compact(pages[0]), compact(" ".join(pages))
    require(first, "证券代码:000035", "中国天楹股份有限公司", MEMBER, LEAD)
    if key == "issuer_award":
        require(first, "TY2026-03", PROJECT, BUYER, "32,976,000.00元/年", "98,928,000.00元")
        require(full, "尚未与采购人签署正式协议", "2026年3月12日")
        return {"stage": "ISSUER_AWARD_NOTICE", "document_date": "2026-03-12", "project_id": PROJECT,
                "lead": LEAD, "member": MEMBER, "buyer": BUYER, "consortium_total_cny": TOTAL,
                "annual_cny": ANNUAL, "issuer_reported_agreement_signed": False}
    if key != "issuer_agreement":
        raise ValueError("PROCUREMENT_SCOPE")
    require(first, "TY2026-06", "TY2026-03", "全资子公司", "签订了", BUYER, "8181.63万元")
    require(full, "2026年4月1日至2029年3月31日", "98,928,000.00元", "32,976,000.00元",
            "本季度服务费在下季度第一个月内予以支付", "未提供发票前甲方有权拒付服务费",
            "若考核结果未达到标准", "服务费扣减", "2026年3月27日")
    return {"stage": "ISSUER_AGREEMENT_NOTICE", "document_date": "2026-03-27",
            "linked_award_notice": "TY2026-03", "lead": LEAD, "member": MEMBER, "buyer": BUYER,
            "consortium_total_cny": TOTAL, "annual_cny": ANNUAL, "service_start": "2026-04-01",
            "service_end_inclusive": "2029-03-31", "prior_three_year_reported_transactions_cny": 81_816_300,
            "issuer_reported_agreement_signed": True, "payment": "QUARTERLY_NEXT_MONTH_INVOICE_CONDITIONAL",
            "performance_deduction_risk": True, "actual_signed_original_seen": False}


def retrieve_html(key: str) -> tuple[bytes, str]:
    with httpx.Client(timeout=8, follow_redirects=False) as client:
        with client.stream("GET", URLS[key], headers={"Accept-Encoding": "identity"}) as response:
            if response.status_code != 200 or response.headers.get("content-encoding", "identity") not in {"identity", ""}:
                raise ValueError("PROCUREMENT_HTTP_" + str(response.status_code))
            if response.headers.get("content-range") is not None:
                raise ValueError("PROCUREMENT_PARTIAL")
            body = bytearray()
            for chunk in response.iter_raw():
                if len(body) + len(chunk) > LIMIT:
                    raise ValueError("PROCUREMENT_OVERSIZE")
                body.extend(chunk)
            length = response.headers.get("content-length")
            if length is not None and (not length.isdecimal() or int(length) != len(body)):
                raise ValueError("PROCUREMENT_LENGTH")
    return bytes(body), datetime.now(UTC).isoformat()


def child(key: str, path: Path) -> None:
    out = {"key": key, "url": URLS[key], "started_at": datetime.now(UTC).isoformat()}
    try:
        if key.startswith("issuer_"):
            obs = retrieve_pdf_bytes(URLS[key], max_bytes=LIMIT)
            body, retrieved = obs.data, obs.retrieved_at
        else:
            body, retrieved = retrieve_html(key)
        out |= {"status": "OBSERVED", "body": base64.b64encode(body).decode("ascii"),
                "sha256": hashlib.sha256(body).hexdigest(), "retrieved_at": retrieved}
    except Exception as exc:
        msg = str(exc)
        out |= {"status": "BLOCK", "error": msg if re.fullmatch(r"[A-Z0-9_]{3,80}", msg) else type(exc).__name__}
    out["finished_at"] = datetime.now(UTC).isoformat()
    write_worker_result(path, out, max_bytes=3 * LIMIT)


def observe(key: str) -> dict:
    before = datetime.now(UTC)
    worker = run_json_worker((sys.executable, "-m", "investment_evidence_engine.public_procurement_chain",
                              "--child", key), timeout_seconds=30, max_bytes=3 * LIMIT)
    out = {"key": key, "url": URLS[key], "status": "BLOCK", "worker_status": worker.status,
           "elapsed_seconds": worker.elapsed_seconds, "raw_body_retained": False}
    if worker.status != "OK" or worker.payload is None:
        return out
    try:
        p = worker.payload
        start, end = (datetime.fromisoformat(p[k]) for k in ("started_at", "finished_at"))
        if (p["key"], p["url"]) != (key, URLS[key]) or not before <= start <= end <= datetime.now(UTC):
            raise ValueError("PROCUREMENT_SCOPE_OR_CLOCK")
        out |= {"started_at": p["started_at"], "finished_at": p["finished_at"]}
        if p["status"] != "OBSERVED":
            return out | {"error": p.get("error", "CHILD_BLOCK")}
        retrieved = datetime.fromisoformat(p["retrieved_at"])
        if not start <= retrieved <= end:
            raise ValueError("PROCUREMENT_CLOCK")
        raw = base64.b64decode(p["body"], validate=True)
        if not 0 < len(raw) <= LIMIT or hashlib.sha256(raw).hexdigest() != p["sha256"]:
            raise ValueError("PROCUREMENT_HASH")
        out |= {"bytes": len(raw), "sha256": p["sha256"], "parent_rehash": "MATCH",
                "retrieved_at": p["retrieved_at"]}
        if key.startswith("issuer_"):
            validate_pdf_shape(raw, max_bytes=LIMIT)
            reader = PdfReader(io.BytesIO(raw), strict=True)
            if reader.is_encrypted or not 1 <= len(reader.pages) <= 4:
                raise ValueError("PROCUREMENT_PAGE_SCOPE")
            pages = tuple(page.extract_text() or "" for page in reader.pages)
            out["page_sha256"] = [hashlib.sha256(compact(page).encode()).hexdigest() for page in pages]
            fields = parse_issuer(key, pages)
        else:
            fields = parse_government(key, raw.decode("utf-8-sig"))
        return out | {"status": "OBSERVED", "fields": fields}
    except Exception as exc:
        msg = str(exc)
        return out | {"error": msg if re.fullmatch(r"[A-Z0-9_]{3,80}", msg) else type(exc).__name__}


def summarize(rows: list[dict]) -> dict:
    good = {row["key"]: row["fields"] for row in rows if row["status"] == "OBSERVED"}
    keys = {"award", "issuer_award", "issuer_agreement"}
    matching = keys <= good.keys() and all(
        len({good[k][field] for k in keys}) == 1
        for field in ("buyer", "lead", "member", "consortium_total_cny")
    ) and good["award"]["project_id"] == good["issuer_award"]["project_id"]
    return {"status": "WARN" if matching else "BLOCK", "observations": rows,
            "award_counterparty_crosscheck": bool(matching), "same_project_not_multiple_awards": bool(matching),
            "tender_budget_distinct_from_award": "tender" in good and "award" in good and
                good["tender"]["budget_cny"] > good["award"]["consortium_total_cny"],
            "issuer_share_of_contract_cny": None, "recognized_revenue_cny": None, "received_cash_cny": None,
            "actual_signed_contract_observed": False, "actual_performance_verified": False,
            "historical_first_availability_verified": False, "durable_original_bytes_verified": False,
            "historical_pit": False, "research_only": True, "decision_authority": False,
            "execution_allowed": False}


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(observe, URLS))
    result = summarize(rows) | {"executor_commit": os.environ["GITHUB_SHA"],
                                "observed_cutoff": datetime.now(UTC).isoformat()}
    print("PUBLIC_PROCUREMENT_CHAIN " + json.dumps(result, sort_keys=True, ensure_ascii=False,
                                                     allow_nan=False), flush=True)
    return 0 if result["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child" and sys.argv[2] in URLS:
        child(sys.argv[2], Path(sys.argv[3]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
