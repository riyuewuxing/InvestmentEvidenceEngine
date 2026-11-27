"""Fixed A/H issuer release-time and financial-unit reconciliation.

Publisher-reported minute is NOT independently witnessed historical bytes.
No raw source retention, full-universe inference or decision admission.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from .bounded_worker import run_json_worker, write_worker_result
from .evidence_time_guard import source_visible
from .official_pdf_transport import read_bounded_pdf

REPO = "riyuewuxing/InvestmentEvidenceEngine"
MODULE = "investment_evidence_engine.cross_exchange_release_control"
URLS = {
    "index": "https://www1.hkexnews.hk/search/titlesearch.xhtml?category=0&from=20070625&lang=EN&market=SEHK&stockId=2696&t1code=10000&t2Gcode=3&t2code=13400&to=20260923",
    "hk": "https://www1.hkexnews.hk/listedco/listconews/sehk/2024/0828/2024082800846.pdf",
    "sz": "https://disc.static.szse.cn/disc/disk03/finalpage/2024-08-28/e1dfbd94-fe97-4eec-b251-2d7866493ac8.PDF",
}
MAX_BYTES = 8 * 1024 * 1024
HK_PRIOR_SHA = "26a35387d756dc436ac9dc536f92af3cf2359ab8df47fc20459f2d7058aeb0de"
HK = ZoneInfo("Asia/Hong_Kong")
RELEASE = "28/08/2024 17:55"
PERIOD_END = "2024-06-30"
EXPECTED = {
    "revenue": ("301126713000", "260124143000"),
    "parent_profit": ("13631257000", "10954145000"),
    "operating_cashflow": ("14178310000", "81971177000"),
}
NUM_THOUSAND = r"[0-9]{1,3}(?:,[0-9]{3})+"
NUM_YUAN = NUM_THOUSAND + r"\.[0-9]{2}"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


class IndexRows(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.current = ([], [])
        elif tag == "a" and self.current is not None:
            self.current[1].extend(v for k, v in attrs if k == "href" and v)

    def handle_data(self, data):
        if self.current is not None:
            self.current[0].append(data)

    def handle_endtag(self, tag):
        if tag == "tr" and self.current is not None:
            self.rows.append(self.current)
            self.current = None


def parse_index(html: str) -> dict:
    parser = IndexRows()
    parser.feed(html)
    parser.close()
    candidates = []
    for parts, links in parser.rows:
        exact = [link for link in links if urljoin(URLS["index"], link) == URLS["hk"]]
        if not exact:
            continue
        text = " ".join(" ".join(parts).split())
        candidates.append((text, len(exact)))
    if len(candidates) != 1 or candidates[0][1] != 1:
        raise ValueError("INDEX_EXACT_DOCUMENT_ROW_REQUIRED")
    text = candidates[0][0]
    stamps = re.findall(r"\b[0-9]{2}/[0-9]{2}/[0-9]{4}\s+[0-9]{2}:[0-9]{2}\b", text)
    if stamps != [RELEASE] or not all(re.search(p, text, re.I) for p in (
            r"\b01211\b", r"\b81211\b", r"BYD COMPANY", r"2024 INTERIM RESULTS ANNOUNCEMENT")):
        raise ValueError("INDEX_RELEASE_OR_IDENTITY_CONFLICT")
    start = datetime.strptime(stamps[0], "%d/%m/%Y %H:%M").replace(tzinfo=HK)
    return {"publisher_release_minute_start": start.isoformat(),
            "conservative_minute_end_exclusive": (start + timedelta(minutes=1)).isoformat(),
            "precision": "MINUTE", "timezone_basis": "HKEX_HONG_KONG_LOCAL",
            "exact_document_link": True, "historical_first_availability_verified": False}


def row_pair(text: str, label: str, *, scale: int, note: bool = False) -> tuple[str, str]:
    # Collapse line wraps, but not number separators: adjacent cells must be distinct.
    text = " ".join(normalize(text).split())
    pattern = r"\s*".join(re.escape(ch) for ch in label)
    num = NUM_THOUSAND if scale == 1000 else NUM_YUAN
    regex = pattern + (r"\s+4" if note else "") + r"\s+(" + num + r")\s+(" + num + r")(?![0-9,.])"
    matches = re.findall(regex, text)
    if len(matches) != 1:
        raise ValueError("FINANCIAL_ROW_MISSING_OR_AMBIGUOUS")
    values = tuple(format((Decimal(v.replace(",", "")) * scale).normalize(), "f") for v in matches[0])
    return values


def parse_sz(pages: dict[int, str]) -> dict:
    first = "".join(normalize(pages[0]).split())
    last = "".join(normalize(pages[3]).split())
    if not all(v in first for v in ("比亚迪股份有限公司2024年半年度报告摘要", "002594", "01211", "81211", "2024-069")):
        raise ValueError("SZ_IDENTITY")
    if "董事会批准报送日期:2024年8月28日" not in last:
        raise ValueError("SZ_BOARD_DATE")
    return {"report_period_end": PERIOD_END, "board_approval_day": "2024-08-28",
            "publisher_path_day": "2024-08-28", "source_unit": "CNY",
            "values_cny": {
                "revenue": row_pair(pages[0], "营业收入(元)", scale=1),
                "parent_profit": row_pair(pages[0], "归属于上市公司股东的净利润(元)", scale=1),
                "operating_cashflow": row_pair(pages[1], "经营活动产生的现金流量净额(元)", scale=1),
            }, "publication_clock_verified": False}


def hk_english_pair(text: str, label: str, *, note: bool = False) -> tuple[str, str]:
    """Use English row anchor; bilingual PDF glyphs may not map to Unicode."""
    compact = " ".join(normalize(text).split())
    pattern = r"\s*".join(re.escape(ch) for ch in label if not ch.isspace())
    # The intervening translation may contain unmapped glyphs but no numeric
    # cells. A note number is fixed by the reviewed original table geometry.
    regex = pattern + r"[^0-9]{0,120}?" + (r"4\s+" if note else "") + "(" + NUM_THOUSAND + r")\s+(" + NUM_THOUSAND + r")(?![0-9,.])"
    matches = re.findall(regex, compact, re.I)
    if len(matches) != 1:
        raise ValueError("HK_ENGLISH_ROW_MISSING_OR_AMBIGUOUS")
    return tuple(format((Decimal(v.replace(",", "")) * 1000).normalize(), "f") for v in matches[0])


def hk_parse_diagnostics(pages: dict[int, str]) -> dict:
    labels = {43: "Operating revenue", 44: "Net profit attributable to shareholders of the parent company", 48: "Net cash flow from operating activities"}
    result = {}
    for i, label in labels.items():
        text = normalize(pages[i])
        compact = "".join(text.split())
        label_pattern = r"\s*".join(re.escape(ch) for ch in label if not ch.isspace())
        hits = list(re.finditer(label_pattern, text, re.I))
        shapes = []
        for hit in hits[:3]:
            fragment = text[max(0, hit.start()-60):hit.end()+120]
            # Preserve only punctuation, digits and whitespace geometry.
            shapes.append(re.sub(r"[^0-9,.() \n\t-]", "X", fragment))
        unit_shape = []
        for m in list(re.finditer(r"RMB", compact))[:3]:
            unit_shape.append(re.sub(r"[^A-Z0-9'’‘]", "X", compact[m.start():m.end()+10]))
        result[str(i)] = {"label_count": len(hits), "shapes": shapes, "unit_shape": unit_shape,
                          "current_period": "30June2024" in compact, "comparative_period": "30June2023" in compact}
    return result


def parse_hk(pages: dict[int, str]) -> dict:
    cover = "".join(normalize(pages[0]).split())
    profile = "".join(normalize(pages[1]).split())
    if not all(v in cover for v in ("BYDCOMPANYLIMITED", "01211", "81211", "2024INTERIMRESULTSANNOUNCEMENT", "30June2024", "28August2024")) or "002594" not in profile:
        raise ValueError("HK_IDENTITY")
    for i, title in ((43, "ConsolidatedIncomeStatement"), (44, "ConsolidatedIncomeStatement"), (48, "ConsolidatedCashFlowStatement")):
        compact = "".join(normalize(pages[i]).split()).replace("’", "'")
        if title not in compact or "RMB'000" not in compact or "30June2024" not in compact or "30June2023" not in compact:
            raise ValueError("HK_PERIOD_OR_UNIT")
    return {"report_period_end": PERIOD_END, "document_declared_day": "2024-08-28", "source_unit": "CNY_THOUSANDS",
            "values_cny": {
                "revenue": hk_english_pair(pages[43], "Operating revenue", note=True),
                "parent_profit": hk_english_pair(pages[44], "Net profit attributable to shareholders of the parent company"),
                "operating_cashflow": hk_english_pair(pages[48], "Net cash flow from operating activities"),
            }}


def reconcile(index: dict, hk: dict, sz: dict, *, observed_at: datetime) -> dict:
    if observed_at.utcoffset() is None:
        raise ValueError("OBSERVATION_TIME_REQUIRED")
    stamp = datetime.fromisoformat(index["publisher_release_minute_start"])
    end = datetime.fromisoformat(index["conservative_minute_end_exclusive"])
    if not stamp + timedelta(minutes=1) == end or observed_at < end:
        raise ValueError("RELEASE_TIME_ORDER")
    hk_values = {k: tuple(v) for k, v in hk["values_cny"].items()}
    sz_values = {k: tuple(v) for k, v in sz["values_cny"].items()}
    matched = hk_values == sz_values == EXPECTED and hk["report_period_end"] == sz["report_period_end"] == PERIOD_END
    cutoffs = []
    for cutoff in (datetime(2024, 6, 30, 23, 59, 59, tzinfo=HK),
                   datetime(2024, 8, 28, 15, 0, tzinfo=HK), stamp,
                   end, datetime(2024, 8, 29, 9, 30, tzinfo=HK)):
        visible = source_visible(available_at=observed_at, retrieved_at=observed_at,
                                 published_at=stamp, cutoff=cutoff)
        cutoffs.append({"cutoff": cutoff.isoformat(), "declared_release_minute_elapsed": cutoff >= end,
                        "actually_observed_by_cutoff": visible})
    return {"status": "WARN" if matched else "BLOCK", "exact_field_and_comparative_match": matched,
            "same_issuer_different_disclosure_channels": True, "independent_audit_of_issuer_figures": False,
            "same_period_end": PERIOD_END, "cutoffs": cutoffs,
            "historical_first_availability_verified": False, "historical_original_bytes_verified": False,
            "pit_safe": False, "decision_authority": False, "execution_allowed": False}


def child(kind: str, target: Path, result: Path) -> None:
    import httpx
    from pypdf import PdfReader

    url = URLS[kind]
    out = {"status": "BLOCK", "kind": kind, "url": url, "started_at": datetime.now(UTC).isoformat()}
    try:
        with httpx.Client(timeout=httpx.Timeout(10), follow_redirects=False) as client:
            with client.stream("GET", url, headers={"Accept-Encoding": "identity", "User-Agent": "Mozilla/5.0"}) as response:
                if str(response.url) != url:
                    raise ValueError("SOURCE_ROUTE_CHANGED")
                deadline = time.monotonic() + 30
                if kind != "index":
                    raw = read_bounded_pdf(response, deadline)
                else:
                    response.raise_for_status()
                    if response.status_code != 200 or response.headers.get("Content-Range") or response.headers.get("Content-Encoding", "identity").lower() not in ("identity", ""):
                        raise ValueError("INDEX_TRANSPORT_SCOPE")
                    data = bytearray()
                    for chunk in response.iter_raw():
                        if time.monotonic() > deadline or len(data) + len(chunk) > 2 * 1024 * 1024:
                            raise ValueError("INDEX_TRANSPORT_LIMIT")
                        data.extend(chunk)
                    raw = bytes(data)
                    length = response.headers.get("Content-Length")
                    if not raw or length is not None and int(length) != len(raw):
                        raise ValueError("INDEX_LENGTH")
        target.write_bytes(raw)
        out.update(source_bytes=len(raw), source_sha256=digest(raw), observed_at=datetime.now(UTC).isoformat())
        if kind == "hk" and digest(raw) != HK_PRIOR_SHA:
            raise ValueError("HK_PRIOR_VERSION_MISMATCH")
        if kind == "index":
            out["parsed"] = parse_index(raw.decode("utf-8"))
        else:
            reader = PdfReader(target, strict=True)
            expected = 94 if kind == "hk" else 4
            if reader.is_encrypted or len(reader.pages) != expected:
                raise ValueError("PDF_PAGE_SCOPE")
            out["page_count"] = expected
            indices = (0, 1, 43, 44, 48) if kind == "hk" else (0, 1, 3)
            # Two extraction modes; each complete candidate must satisfy the same rules.
            errors = []
            for mode in ("plain", "layout"):
                pages = {i: reader.pages[i].extract_text(extraction_mode=mode) or "" for i in indices}
                try:
                    parsed = parse_hk(pages) if kind == "hk" else parse_sz(pages)
                    out.update(parsed=parsed, extraction_mode=mode, page_text_hashes={str(i): digest(t.encode()) for i, t in pages.items()})
                    break
                except ValueError as exc:
                    errors.append(str(exc))
                    if kind == "hk":
                        out.setdefault("parse_diagnostics", {})[mode] = hk_parse_diagnostics(pages)
            if "parsed" not in out:
                out["parse_errors"] = errors
                raise ValueError("PDF_SEMANTIC_PARSE")
        out["status"] = "OBSERVED"
    except Exception as exc:
        out["error_type"] = type(exc).__name__
        if type(exc) is ValueError:
            out["error_code"] = str(exc)[:120]
    write_worker_result(result, out)


def hk_only() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    with TemporaryDirectory() as folder:
        target = Path(folder) / "hk"
        worker = run_json_worker((sys.executable, "-m", MODULE, "--child", "hk", str(target)),
                                 timeout_seconds=45, max_bytes=65536)
        data = worker.payload or {"status": "BLOCK"}
        data.update(worker_status=worker.status, elapsed_seconds=worker.elapsed_seconds)
        data["parent_rehash"] = "MATCH" if target.is_file() and digest(target.read_bytes()) == data.get("source_sha256") == HK_PRIOR_SHA else "NOT_VERIFIED"
        if data["parent_rehash"] != "MATCH":
            data["status"] = "BLOCK"
    report = {"status": "WARN" if data["status"] == "OBSERVED" else "BLOCK", "executor_commit": os.environ["GITHUB_SHA"],
              "observation": data, "raw_source_retained": False, "decision_authority": False, "pit_safe": False}
    print("PUBLIC_CROSS_EXCHANGE_HK_ONLY " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    observations = {}
    with TemporaryDirectory() as folder:
        for kind in URLS:
            target = Path(folder) / kind
            worker = run_json_worker((sys.executable, "-m", MODULE, "--child", kind, str(target)),
                                     timeout_seconds=45, max_bytes=65536)
            data = worker.payload or {"status": "BLOCK"}
            data.update(worker_status=worker.status, elapsed_seconds=worker.elapsed_seconds)
            data["parent_rehash"] = "MATCH" if target.is_file() and digest(target.read_bytes()) == data.get("source_sha256") else "NOT_VERIFIED"
            if data["parent_rehash"] != "MATCH":
                data["status"] = "BLOCK"
            observations[kind] = data
    report = {"status": "BLOCK", "executor_commit": os.environ["GITHUB_SHA"], "observations": observations,
              "raw_source_retained": False, "decision_authority": False, "pit_safe": False,
              "execution_allowed": False}
    if all(v["status"] == "OBSERVED" for v in observations.values()):
        report["reconciliation"] = reconcile(*(observations[k]["parsed"] for k in ("index", "hk", "sz")),
            observed_at=max(datetime.fromisoformat(v["observed_at"]) for v in observations.values()))
        report["status"] = report["reconciliation"]["status"]
    print("PUBLIC_CROSS_EXCHANGE_RELEASE " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--child" and sys.argv[2] in URLS:
        child(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))
    elif sys.argv[1:] == ["--hk-only"]:
        raise SystemExit(hk_only())
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
