"""Fixed official rule PDF observation. No arbitrary route or historical PIT claim."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from investment_evidence_engine.bounded_worker import run_json_worker, write_worker_result
from investment_evidence_engine.execution_obstruction import RULES
from investment_evidence_engine.issuer_revision_control import normalize_text
from investment_evidence_engine.official_pdf_transport import read_bounded_pdf, validate_pdf_shape

REPO = "riyuewuxing/InvestmentEvidenceEngine"
MAX_BYTES = 4 * 1024 * 1024
# Page indices verified against the two separately reviewed versions.
PAGES = {"2023": (10, 11, 12, 23, 24, 26, 27),
         "2026": (11, 12, 13, 25, 27, 28)}
URLS = dict(zip(PAGES, RULES, strict=True))


def parse_rule_pages(year: str, pages: dict[int, str]) -> dict:
    if year not in PAGES or set(pages) != set(PAGES[year]):
        raise ValueError("RULE_PAGE_SCOPE")
    norm = {i: normalize_text(v) for i, v in pages.items()}
    first = PAGES[year][0]
    groups = [
        ((first,), ("3.3.11", "A股交易的申报价格最小变动单位为0.01元人民币")),
        ((first + 1,), ("主板股票的价格涨跌幅限制比例为10%", "3.3.14",
                       "前收盘价×(1±涨跌幅限制比例)", "3.3.15",
                       "首次公开发行上市后的前五个交易日", "重新上市首日", "进入退市整理期的首日")),
        ((first + 2,), ("3.3.19", "四舍五入原则取至申报价格最小变动单位",
                       "增减一个申报价格最小变动单位", "以申报价格最小变动单位作为相应价格")),
        ((23, 24) if year == "2023" else (25,),
         ("4.4.2", "证券发行人认为有必要调整上述计算公式时",
          "经本所同意的", "4.4.3", "参考价作为计算涨跌幅度的基准")),
        ((26, 27) if year == "2023" else (28,),
         ("5.2.3", "证券除权(息)日", "前收盘价为该证券除权(息)参考价")),
    ]
    for indexes, markers in groups:
        # A page footer can intervene at the boundary, so check clause
        # fragments rather than join an assumed contiguous sentence.
        combined = "".join(norm[i] for i in indexes)
        if not all(normalize_text(marker) in combined for marker in markers):
            raise ValueError("RULE_REVIEWED_TEXT_MISMATCH")
    return {"ordinary_main_board_limit_pct": 10, "a_share_tick_cny": "0.01",
            "rounding": "HALF_UP_TO_TICK_WITH_MINIMUM_TICK_MOVEMENT",
            "ex_date_reference_basis": True, "issuer_formula_adjustment_requires_exchange_consent": True,
            "rule_clauses_checked": ["3.3.11", "3.3.13-15", "3.3.19", "4.4.2-3", "5.2.3"]}


def child(year: str, out: Path) -> None:
    import httpx

    # Only the two compiled-in rules routes, not a caller-controlled URL.
    url = URLS[year]
    start = datetime.now(UTC).isoformat()
    with httpx.Client(timeout=httpx.Timeout(5.0), follow_redirects=False) as client:
        with client.stream("GET", url, headers={"Accept": "application/pdf",
                                                  "Accept-Encoding": "identity"}) as response:
            status = response.status_code
            if status != 200:
                write_worker_result(out, {"year": year, "url": url, "http_status": status})
                return
            raw = read_bounded_pdf(response, time.monotonic()+12, max_bytes=MAX_BYTES)
    write_worker_result(out, {"year": year, "url": url, "http_status": status,
        "started": start, "retrieved": datetime.now(UTC).isoformat(),
        "sha256": hashlib.sha256(raw).hexdigest(), "body": base64.b64encode(raw).decode("ascii")})


def observe(year: str, folder: Path) -> dict:
    from pypdf import PdfReader

    out = {"year": year, "url": URLS[year], "status": "BLOCK", "original_bytes_retained": False,
           "historical_availability_verified": False}
    r = run_json_worker((sys.executable, __file__, "--child", year), timeout_seconds=22,
                        max_bytes=6*1024*1024)
    out |= {"worker": r.status, "elapsed_seconds": r.elapsed_seconds}
    if r.status != "OK" or r.payload is None:
        return out
    p = r.payload
    try:
        if p["year"] != year or p["url"] != URLS[year]:
            raise ValueError("RULE_SOURCE_SCOPE")
        out["http_status"] = p["http_status"]
        if p["http_status"] != 200:
            return out
        start, end = (datetime.fromisoformat(p[k]) for k in ("started", "retrieved"))
        if not start.tzinfo or not end.tzinfo or not start <= end <= datetime.now(UTC):
            raise ValueError("RULE_TIME_SCOPE")
        raw = base64.b64decode(p["body"], validate=True)
        validate_pdf_shape(raw, max_bytes=MAX_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != p["sha256"]:
            raise ValueError("RULE_DIGEST")
        path = folder/(year+".pdf")
        with path.open("xb") as handle:
            handle.write(raw)
        reopened = path.read_bytes()
        if reopened != raw:
            raise ValueError("RULE_REOPEN")
        out |= {"bytes": len(raw), "sha256": digest, "parent_rehash": "MATCH",
                "temporary_rehash": "MATCH", "started": p["started"], "retrieved": p["retrieved"]}
        reader = PdfReader(io.BytesIO(reopened), strict=True)
        if reader.is_encrypted or not max(PAGES[year]) < len(reader.pages) <= 80:
            raise ValueError("RULE_PDF_PAGE_COUNT")
        if normalize_text("深圳证券交易所交易规则") not in normalize_text(reader.pages[0].extract_text() or ""):
            raise ValueError("RULE_TITLE")
        if normalize_text(year+"年修订") not in normalize_text(reader.pages[0].extract_text() or ""):
            raise ValueError("RULE_VERSION")
        pages = {i: reader.pages[i].extract_text() or "" for i in PAGES[year]}
        out |= {"page_count": len(reader.pages), "page_text_sha256": {
            str(i+1): hashlib.sha256(normalize_text(v).encode()).hexdigest() for i, v in pages.items()}}
        out["fields"] = parse_rule_pages(year, pages)
        return out | {"status": "OBSERVED"}
    except Exception as exc:  # noqa: BLE001 - fixed source parser boundary.
        return out | {"error": str(exc) if str(exc).startswith("RULE_") else type(exc).__name__}


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    with TemporaryDirectory() as temp:
        documents = [observe(year, Path(temp)) for year in URLS]
    status = "WARN" if all(d["status"] == "OBSERVED" for d in documents) else "BLOCK"
    print("PUBLIC_SZSE_RULE_OBSERVATION " + json.dumps({
        "executor_commit": os.environ["GITHUB_SHA"], "status": status, "documents": documents,
        "historical_availability_verified": False, "full_rule_history_verified": False,
        "decision_authority": False, "execution_allowed": False}, sort_keys=True), flush=True)
    return 0 if status == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child" and sys.argv[2] in URLS:
        child(sys.argv[2], Path(sys.argv[3]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
