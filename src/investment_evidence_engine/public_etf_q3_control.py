"""Fixed, bounded two-ETF 2026 Q3 original-document control.

Official issuer/exchange routes, current retrieval only; no historical capture
or benchmark-index vintage, raw document redistribution or trading authority.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from .bounded_worker import run_json_worker, write_worker_result
from .etf_report_diagnostics import compare_reports, evaluate_report
from .issuer_revision_control import normalize_text
from .official_pdf_transport import read_bounded_pdf, validate_pdf_shape

REPO = "riyuewuxing/InvestmentEvidenceEngine"
MAX_BYTES = 2 * 1024 * 1024
DOCS = {
    "510330": {
        "url": "https://accountquery.chinaamc.com/front/front/file/preview/8d2d29d1dd5227dc7a92f89a4203b709/%E5%8D%8E%E5%A4%8F%E6%B2%AA%E6%B7%B1300%E4%BA%A4%E6%98%93%E5%9E%8B%E5%BC%80%E6%94%BE%E5%BC%8F%E6%8C%87%E6%95%B0%E8%AF%81%E5%88%B8%E6%8A%95%E8%B5%84%E5%9F%BA%E9%87%912026%E5%B9%B4%E7%AC%AC3%E5%AD%A3%E5%BA%A6%E6%8A%A5%E5%91%8A.pdf",
        "title": "华夏沪深300交易型开放式指数证券投资基金",
        "cover_date": "二〇二六年十月二十七日",
        "page_count": 17, "overview": 3, "financial": 3, "performance": 4, "shares": 15,
        "source_type": "MANAGER_OFFICIAL_FIXED_PREVIEW",
    },
    "510320": {
        "url": "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-10-27/510320_20261027_6GPH.pdf",
        "title": "中金沪深300交易型开放式指数证券投资基金",
        "cover_date": "2026年10月27日",
        "page_count": 11, "overview": 2, "financial": 3, "performance": 3, "shares": 10,
        "source_type": "EXCHANGE_OFFICIAL_FIXED_PDF",
    },
}
EXPECTED_SHA256 = {
    "510330": "f0b3d948633558c55317fbc852257eb9657dfef3c47e89d5a9e5fe80ab099826",
    "510320": "bce1bb11a2e0898b37f174ebbb96bba30794167a0cffc4e8b3182365dd86241c",
}
NUM = r"(?:[1-9][0-9]{0,2}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?"
PCT = r"(-?[0-9]{1,3}\.[0-9]{2})%"
PERF_LABELS = {"3M": "过去三个月", "6M": "过去六个月", "1Y": "过去一年"}
PERF_FIELDS = ("nav_return_pct", "nav_std_pct", "benchmark_return_pct",
               "benchmark_std_pct", "return_difference_pp", "std_difference_pp")


def compact(text: str) -> str:
    return normalize_text(text).translate(str.maketrans({c: "-" for c in "−–—‐‑‒﹣－"}))


def one(pattern: str, text: str, code: str) -> str:
    values = re.findall(pattern, text)
    if len(values) != 1 or not isinstance(values[0], str):
        raise ValueError(code)
    return values[0]


def amount(label: str, text: str, code: str, *, signed: bool = False) -> str:
    pattern = label + r"(" + (r"-?" if signed else "") + NUM + r")(?![0-9.,])"
    return one(pattern, text, code).replace(",", "")


def section(text: str, start: str, end: str, code: str) -> str:
    if text.count(start) != 1:
        raise ValueError(code)
    rest = text.split(start, 1)[1]
    if end not in rest:
        raise ValueError(code)
    return rest.split(end, 1)[0]


def parse_pages(symbol: str, pages: dict[int, str]) -> dict:
    """Read actual rows by page/section/label, not search-result cells."""
    doc = DOCS[symbol]
    required = {1, 2, doc["overview"], doc["financial"], doc["performance"], doc["shares"]}
    if set(pages) != required or any(not isinstance(v, str) or not v for v in pages.values()):
        raise ValueError("ETF_Q3_PAGE_SCOPE")
    texts = {k: compact(v) for k, v in pages.items()}
    cover = texts[1]
    if not all(x in cover for x in (doc["title"], "2026年第3季度报告", "2026年9月30日",
                                     "报告送出日期", doc["cover_date"])):
        raise ValueError("ETF_Q3_COVER_SCOPE")
    notice = texts[2]
    if (not re.search(r"本报告期自2026年0?7月0?1日起至(?:2026年)?0?9月30日止", notice)
            or "财务资料未经审计" not in notice):
        raise ValueError("ETF_Q3_PERIOD_OR_AUDIT_SCOPE")
    overview = texts[doc["overview"]]
    if ("基金主代码" + symbol not in overview or "交易型开放式" not in overview):
        raise ValueError("ETF_Q3_ISSUER_SCOPE")
    # Match the source's own benchmark label, not a constructed total-return index.
    benchmark = one(r"业绩比较基准(?:本基金业绩比较基准为)?(沪深300指数(?:收益率)?)[。.]?(?=风险收益特征)",
                    overview, "ETF_Q3_BENCHMARK_LABEL")
    end_label = r"报告期(?:期)?末基金份额总额"
    overview_units = amount(end_label, overview, "ETF_Q3_OVERVIEW_UNITS")
    financial = texts[doc["financial"]]
    if "主要财务指标" not in financial or "期末基金份额净值" not in financial:
        raise ValueError("ETF_Q3_FINANCIAL_SECTION")
    financial = financial.split("主要财务指标", 1)[1]
    if "3.2基金净值表现" in financial:
        financial = financial.split("3.2基金净值表现", 1)[0]
    # Compaction joins a value and the ordinal of the next row. Anchor each
    # monetary cell to both its own label and the next label; do not infer digits.
    financial = financial.split("注:", 1)[0]
    money = r"(-?(?:[1-9][0-9]{0,2}(?:,[0-9]{3})+|[0-9]+)\.[0-9]{2})"
    nav_cell = r"([0-9]+\.[0-9]{4})"
    def financial_cell(label: str, following: str, pattern: str, code: str) -> str:
        return one(label + pattern + r"(?=" + following + r")", financial, code).replace(",", "")
    assets = financial_cell("期末基金资产净值", r"(?:5[.、])?期末基金份额净值", money, "ETF_Q3_ASSETS")
    nav = one(r"期末基金份额净值" + nav_cell + r"(?![0-9.,])", financial, "ETF_Q3_NAV")
    realized = financial_cell("本期已实现收益", r"(?:2[.、])?本期利润", money, "ETF_Q3_REALIZED")
    profit = financial_cell("本期利润", r"(?:3[.、])?加权平均基金份额本期利润", money, "ETF_Q3_PROFIT")
    perf = texts[doc["performance"]]
    if "3.2.1基金份额净值增长率及其与同期业绩比较基准收益率的比较" not in perf:
        raise ValueError("ETF_Q3_PERFORMANCE_SECTION")
    perf = section(perf, "3.2.1基金份额净值增长率及其与同期业绩比较基准收益率的比较",
                   "3.2.2", "ETF_Q3_PERFORMANCE_SECTION")
    performance = {}
    for horizon, label in PERF_LABELS.items():
        values = re.findall(re.escape(label) + PCT * 6, perf)
        if len(values) != 1:
            raise ValueError("ETF_Q3_PERFORMANCE_ROW_" + horizon)
        performance[horizon] = dict(zip(PERF_FIELDS, values[0], strict=True))
    shares = texts[doc["shares"]]
    if "§7" not in shares:
        raise ValueError("ETF_Q3_SHARE_SECTION")
    shares = shares.split("§7", 1)[0]
    split = one(r"报告期(?:期)?间基金拆分变动份额(?:\(份额减少以[“\"']?-[”\"']?填列\))?(-|" + NUM + r"|-" + NUM + r")(?=报告期)",
                shares, "ETF_Q3_SPLIT_ROW")
    fields = {
        "symbol": symbol, "period_start": "2026-07-01", "period_end": "2026-09-30",
        "declared_report_day": "2026-10-27", "benchmark_label": benchmark,
        "end_assets_cny": assets, "end_nav_cny": nav, "overview_end_units": overview_units,
        "begin_units": amount(r"报告期(?:期)?初基金份额总额", shares, "ETF_Q3_BEGIN_UNITS"),
        "created_units": amount(r"报告期(?:期)?间基金总申购份额", shares, "ETF_Q3_CREATED_UNITS"),
        "redeemed_units": amount(r"报告期(?:期)?间基金总赎回份额", shares, "ETF_Q3_REDEEMED_UNITS"),
        "split_units_label": "DASH" if split == "-" else split.replace(",", ""),
        "end_units": amount(end_label, shares, "ETF_Q3_END_UNITS"),
        "realized_profit_cny": realized, "profit_cny": profit, "performance": performance,
    }
    evaluate_report(fields)
    return fields


def _child(symbol: str, path: Path) -> None:
    import httpx

    url = DOCS[symbol]["url"]
    started = datetime.now(UTC)
    info = {"symbol": symbol, "url": url, "started_at": started.isoformat()}
    try:
        with httpx.Client(timeout=5.0, follow_redirects=False) as client:
            with client.stream("GET", url, headers={"Accept-Encoding": "identity",
                                                     "Accept": "application/pdf"}) as response:
                info["http_status"] = response.status_code
                if str(response.url) != url:
                    raise ValueError("ETF_Q3_URL_CHANGED")
                raw = read_bounded_pdf(response, time.monotonic()+20, max_bytes=MAX_BYTES)
        info |= {"retrieved_at": datetime.now(UTC).isoformat(),
                 "body_sha256": hashlib.sha256(raw).hexdigest(),
                 "body": base64.b64encode(raw).decode("ascii")}
    except Exception as exc:  # noqa: BLE001 - do not publish third-party error text.
        info["error_type"] = type(exc).__name__
    write_worker_result(path, info, max_bytes=3*MAX_BYTES)


def observe(symbol: str, folder: Path) -> dict:
    from pypdf import PdfReader

    doc = DOCS[symbol]
    out = {"symbol": symbol, "url": doc["url"], "source_type": doc["source_type"],
           "status": "BLOCK", "raw_body_retained": False}
    started = datetime.now(UTC)
    task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.public_etf_q3_control",
                            "--child", symbol), timeout_seconds=30, max_bytes=3*MAX_BYTES)
    out |= {"worker_status": task.status, "elapsed_seconds": task.elapsed_seconds}
    if task.status != "OK" or task.payload is None:
        return out
    try:
        p = task.payload
        if (p.get("symbol"), p.get("url")) != (symbol, doc["url"]):
            raise ValueError("ETF_Q3_RECEIPT_SCOPE")
        if "error_type" in p:
            return out | {"http_status": p.get("http_status"), "error_type": p["error_type"]}
        begin, end = (datetime.fromisoformat(p[k]) for k in ("started_at", "retrieved_at"))
        if (begin.utcoffset() is None or end.utcoffset() is None
                or not started <= begin <= end <= datetime.now(UTC) or p["http_status"] != 200):
            raise ValueError("ETF_Q3_RECEIPT_CLOCK")
        raw = base64.b64decode(p["body"], validate=True)
        validate_pdf_shape(raw, max_bytes=MAX_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != p["body_sha256"] or digest != EXPECTED_SHA256[symbol]:
            raise ValueError("ETF_Q3_BODY_HASH")
        target = folder / (symbol + ".pdf")
        with target.open("xb") as handle:
            handle.write(raw)
        reopened = target.read_bytes()
        if reopened != raw or hashlib.sha256(reopened).hexdigest() != digest:
            raise ValueError("ETF_Q3_REOPEN_HASH")
        out |= {"sha256": digest, "bytes": len(raw), "parent_rehash": "MATCH",
                "temporary_rehash": "MATCH", "retrieved_at": end.isoformat()}
        reader = PdfReader(io.BytesIO(reopened), strict=True)
        if reader.is_encrypted or len(reader.pages) != doc["page_count"]:
            raise ValueError("ETF_Q3_PAGE_COUNT")
        required = {1, 2, doc["overview"], doc["financial"], doc["performance"], doc["shares"]}
        pages = {i: reader.pages[i-1].extract_text() or "" for i in sorted(required)}
        out |= {"page_count": len(reader.pages), "selected_page_text_sha256": {
            str(i): hashlib.sha256(compact(text).encode()).hexdigest() for i, text in pages.items()}}
        # A limited diagnostic cell is logged only on parse failure, not the
        # report text or table. It makes a typography mismatch inspectable.
        try:
            fields = parse_pages(symbol, pages)
        except ValueError as exc:
            if str(exc) == "ETF_Q3_SPLIT_ROW":
                share_page = compact(pages[doc["shares"]])
                cell = re.search(r"基金拆分变动份额(.{0,60}?)(?=报告期(?:期)?末基金份额总额)", share_page)
                out["split_cell_probe"] = cell.group(1) if cell else None
            raise
        out |= {"fields": fields, "diagnostic": evaluate_report(fields), "status": "OBSERVED"}
    except Exception as exc:  # noqa: BLE001 - explicit failure, not fallback values.
        msg = str(exc)
        out["error"] = msg if re.fullmatch(r"ETF_[A-Z0-9_]+", msg) else type(exc).__name__
    return out


def run_control() -> dict:
    with TemporaryDirectory() as temp:
        docs = [observe(symbol, Path(temp)) for symbol in DOCS]
    report = {"status": "BLOCK", "documents": docs, "retrospective_only": True,
              "historical_first_availability_verified": False, "pit_safe": False,
              "decision_authority": False, "execution_allowed": False}
    if all(d["status"] == "OBSERVED" for d in docs):
        try:
            report["comparison"] = compare_reports(docs[0]["fields"], docs[1]["fields"])
            report["status"] = "WARN"
        except ValueError as exc:
            report["comparison_error"] = str(exc)
    return report


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    report = run_control() | {"executor_commit": os.environ["GITHUB_SHA"]}
    print("PUBLIC_ETF_Q3_CONTROL " + json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child" and sys.argv[2] in DOCS:
        _child(sys.argv[2], Path(sys.argv[3]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
