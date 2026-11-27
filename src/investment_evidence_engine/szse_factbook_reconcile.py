"""Diagnose the exact previous yearbook version against dated CAPCO lists.

Transient raw PDFs only. No whole code roster or table leaves the runner.
The CAPCO half-year label is not a proven effective date or a listing roster.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote

from .bounded_worker import run_json_worker, write_worker_result
from .issuer_revision_control import normalize_text
from .official_pdf_transport import MAX_PDF_BYTES, read_bounded_pdf
from .szse_factbook_control import EXPECTED_LENGTH, REPO, TABLES, parse_rows, summarize_rows

YEARBOOK_SHA = "ce2d0fd45f90284d8cf6a0663c68c61c76dd0250a73ff94da5982a981195cd2e"
YEARBOOK_URL = "https://docs.static.szse.cn/www/market/periodical/year/W020250912366937867370.pdf"
CAPCO_ROOT = "https://capcofile.oss-cn-beijing.aliyuncs.com/"
URLS = {
    "yearbook": YEARBOOK_URL,
    "h1": CAPCO_ROOT+"2024/file/GwFj/"+quote("2024年上半年上市公司行业分类结果（按股票代码排序）.pdf", safe=""),
    "h2": CAPCO_ROOT+"2025/file/"+quote("2024年下半年上市公司行业分类结果（按行业排序）.pdf", safe=""),
    "h1_issuer": "https://static.cninfo.com.cn/finalpage/2024-10-30/1221553847.PDF",
    "h2_issuer": "https://disc.static.szse.cn/disc/disk03/finalpage/2025-08-30/f9523108-47aa-4989-9acd-67429c8d9065.pdf",
}
TOTALS = {"main": Decimal("20587080.87"), "chinext": Decimal("12454072.25")}
START = {"main": 136, "chinext": 230}
BOARD_HASH = {
    "main": "99e19e90602bb77dac946065eaada18ed96fcbea67f7e373bd2c05db74940a93",
    "chinext": "1d66b5d33770904acea384cbb5240dc5ba3d14957ddde77e8de66f0ed6d6d3cd",
}
CODE = re.compile(r"(?<![0-9])[0-9]{6}(?![0-9])")
ANCHORS = ("000035", "003020", "002616", "600190", "600837", "601211", "300750", "200028")
PREFIXES = {
    "SZ_MAIN_A": ("000", "001", "002", "003"), "SZ_CHINEXT": ("300", "301"), "SZ_B": ("200",),
    "SH_MAIN_A": ("600", "601", "603", "605"), "SH_STAR": ("688", "689"), "SH_B": ("900",),
    "BSE_LEGACY_OR_920": ("4", "8", "920"),
}


def prefix_group(code: str) -> str:
    return next((name for name, prefixes in PREFIXES.items() if code.startswith(prefixes)), "UNKNOWN")


def digest_projection(rows: object) -> str:
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(",", ":"),
                                    sort_keys=True, allow_nan=False).encode()).hexdigest()


def fetch(key: str, target: Path, receipt: Path) -> None:
    import httpx

    url = URLS[key]
    cap = 18*1024*1024 if key=="yearbook" else MAX_PDF_BYTES
    started = datetime.now(UTC)
    with httpx.Client(timeout=httpx.Timeout(8.0), follow_redirects=False) as client:
        with client.stream("GET", url, headers={"Accept": "application/pdf", "Accept-Encoding": "identity"}) as response:
            if str(response.url) != url:
                raise ValueError("HISTORICAL_SCOPE_SOURCE_URL")
            body = read_bounded_pdf(response, time.monotonic()+35, max_bytes=cap)
    sha = hashlib.sha256(body).hexdigest()
    record = {"url": url, "source_bytes": len(body), "source_sha256": sha,
              "started_at": started.isoformat(), "observed_at": datetime.now(UTC).isoformat()}
    if key=="yearbook" and (len(body)!=EXPECTED_LENGTH or sha!=YEARBOOK_SHA):
        write_worker_result(receipt, record | {"status": "BLOCK", "reason": "YEARBOOK_EXACT_VERSION_CHANGED"})
        return
    with target.open("xb") as f:
        f.write(body)
    write_worker_result(receipt, record | {"status": "OBSERVED"})


def observe(key: str, folder: Path) -> tuple[Path | None, dict]:
    target = folder/(key+".pdf")
    task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.szse_factbook_reconcile",
                            "--fetch", key, str(target)), timeout_seconds=50, max_bytes=65536)
    report = {"status": "BLOCK", "worker_status": task.status, "elapsed_seconds": task.elapsed_seconds,
              "url": URLS[key], "raw_retained": False}
    if task.status!="OK" or task.payload is None:
        return None, report
    data = task.payload
    report |= data
    if data.get("status")!="OBSERVED" or not target.is_file():
        return None, report
    raw = target.read_bytes()
    if len(raw)!=data["source_bytes"] or hashlib.sha256(raw).hexdigest()!=data["source_sha256"]:
        return None, report | {"status": "BLOCK", "reason": "HISTORICAL_SOURCE_REHASH"}
    return target, report | {"parent_rehash": "MATCH"}


def duplicate_records(rows: list[tuple], col: int) -> list[dict]:
    count = Counter(r[col] for r in rows)
    return [{"code": code, "ranks": [r[0] for r in rows if r[col]==code]}
            for code, n in sorted(count.items()) if n>1]


def row_anomalies(rows: list[tuple], board: str) -> dict:
    prefixes = TABLES[board][3]
    dup = {name: duplicate_records(rows, col) for name, col in (("market", 1), ("negotiable", 2))}
    unexpected = {name: sorted({r[col] for r in rows if not r[col].startswith(prefixes)})
                  for name, col in (("market", 1), ("negotiable", 2))}
    inversions = {name: [{"previous_rank": a[0], "next_rank": b[0], "previous_code": a[col-2],
                          "next_code": b[col-2]} for a, b in zip(rows[:-1], rows[1:], strict=True)
                         if Decimal(a[col])<Decimal(b[col])]
                  for name, col in (("market", 3), ("negotiable", 4))}
    total = sum((Decimal(r[3]) for r in rows), Decimal(0))
    delta = total-TOTALS[board]
    rounding = Decimal("0.005")*(len(rows)+1)
    return {"duplicate_counts": {k: len(v) for k, v in dup.items()},
            "duplicate_details_bounded": {k: v[:30] for k, v in dup.items()},
            "unexpected_prefix_counts": {k: len(v) for k, v in unexpected.items()},
            "unexpected_prefix_codes_bounded": {k: v[:30] for k, v in unexpected.items()},
            "inversion_counts": {k: len(v) for k, v in inversions.items()},
            "inversion_details_bounded": {k: v[:20] for k, v in inversions.items()},
            "market_value_sum_minus_published_million_cny": str(delta),
            "maximum_rounding_difference_million_cny": str(rounding),
            "market_value_sum_within_rounding_bound": abs(delta)<=rounding,
            "unique_market_codes": len({r[1] for r in rows})}


def capco_codes(text: str, *, sorted_by_code: bool) -> tuple[list[str], int]:
    codes = []
    rejected = 0
    for line in text.splitlines():
        matches = CODE.findall(line)
        if not matches:
            continue
        if len(matches)!=1:
            rejected += 1
            continue
        code = matches[0]
        # H1 company code is the first column. H2 company code is in a
        # separate right-hand cell; text may include merged industry columns.
        # Require a company-name-shaped suffix, not a free-floating number.
        suffix = line.split(code, 1)[1].strip()
        if (sorted_by_code and not line.lstrip().startswith(code)) or not re.search(r"[\u3400-\u9fff]", suffix):
            rejected += 1
            continue
        codes.append(code)
    return codes, rejected


def capco_parse(path: Path, key: str) -> tuple[set[str], dict]:
    from pypdf import PdfReader

    reader = PdfReader(path, strict=True)
    if reader.is_encrypted or not 50<=len(reader.pages)<=260:
        raise ValueError("CAPCO_PAGE_SCOPE")
    codes = []
    rejected = 0
    all_text_tokens = []
    page_counts = []
    anchor_lines = {}
    title = "2024年上半年上市公司行业分类结果" if key=="h1" else "2024年下半年上市公司行业分类结果"
    for i, page in enumerate(reader.pages):
        layout = page.extract_text(extraction_mode="layout") or ""
        plain = page.extract_text() or ""
        if i==0 and title not in normalize_text(layout):
            raise ValueError("CAPCO_EDITION_IDENTITY")
        found, bad = capco_codes(layout, sorted_by_code=key=="h1")
        codes.extend(found)
        all_text_tokens.extend(CODE.findall(plain))
        rejected += bad
        page_counts.append(len(found))
        for line in layout.splitlines():
            for code in ANCHORS:
                if CODE.findall(line)==[code] and code in found:
                    # Preserve only anchors used for independently checked
                    # classification facts, not arbitrary table text.
                    if code=="003020" and key=="h1":
                        anchor_lines[code]={"C27": bool(re.search(r"\bC\b.*\b27\b", line))}
                    elif code=="002616" and key=="h2":
                        anchor_lines[code]={"row_present": True}
    unique = set(codes)
    counts = Counter(codes)
    duplicates = sorted(code for code,n in counts.items() if n>1)
    plain_equal = Counter(all_text_tokens)==counts
    monotone = codes==sorted(codes) if key=="h1" else None
    report = {"page_count":len(reader.pages), "rows":len(codes), "unique_codes":len(unique),
        "rejected_candidate_lines":rejected, "layout_vs_plain_code_multiset_match":plain_equal,
        "ascending_code_order":monotone, "duplicate_count":len(duplicates),
        "duplicate_codes_bounded":duplicates[:20], "empty_pages":sum(n==0 for n in page_counts),
        "prefix_groups":dict(sorted(Counter(prefix_group(c) for c in unique).items())),
        "code_set_sha256":digest_projection(sorted(unique)), "anchor_codes_present":{c:c in unique for c in ANCHORS},
        "anchor_field_checks":anchor_lines, "coverage_scope":"ASSOCIATION_COMPANY_CLASSIFICATION_ROWS_NOT_LISTED_SECURITY_REGISTER",
        "publication_clock_verified":False, "historical_vintage_verified":False}
    report["status"]="OBSERVED_CODE_SET_ONLY" if (not rejected and plain_equal and not duplicates
        and (monotone is not False) and all(page_counts) and 4500<=len(unique)<=6000) else "BLOCK"
    return unique, report


def compare_sets(left: set[str], right: set[str]) -> dict:
    return {"left_count":len(left),"right_count":len(right),"intersection":len(left&right),
            "left_only":len(left-right),"right_only":len(right-left),
            "left_only_codes_bounded":sorted(left-right)[:20],"right_only_codes_bounded":sorted(right-left)[:20],
            "left_only_sha256":digest_projection(sorted(left-right)),
            "right_only_sha256":digest_projection(sorted(right-left)),
            "membership_changes_are_not_verified_listings_or_delistings":True}


def issuer_parse(path: Path, key: str) -> dict:
    from pypdf import PdfReader

    reader = PdfReader(path, strict=True)
    first = normalize_text(reader.pages[0].extract_text() or "")
    if key=="h1_issuer":
        identity, code, idxs = "合肥立方制药股份有限公司", "003020", (3,4)
        text = "".join(normalize_text(reader.pages[i].extract_text() or "") for i in idxs)
        marks = ("2024年9月30日", "2024年上半年上市公司行业分类结果", "批发业", "F51", "医药制造业", "C27")
        date, docday, industry = "2024-09-30", "2024-10-30", "C27"
    else:
        identity, code, idxs = "广东长青(集团)股份有限公司", "002616", tuple(range(8,12))
        text = "".join(normalize_text(reader.pages[i].extract_text() or "") for i in idxs)
        marks = ("2025年4月18日", "2024年下半年上市公司行业分类结果", "N77", "生态保护和环境治理业")
        date, docday, industry = "2025-04-18", "2025-08-30", "N77"
    if identity not in first or code not in first or not all(m in text for m in marks):
        raise ValueError("CAPCO_ISSUER_CITATION_FIELDS")
    return {"status":"OBSERVED_ISSUER_REPORTED_RELEASE_DAY","symbol":code,"issuer_reported_release_day":date,
            "issuer_document_day":docday,"industry_code":industry,"checked_pdf_pages":[i+1 for i in idxs],
            "same_original_classification_bytes_at_release_verified":False,"first_availability_verified":False}


def parse_all(folder: Path, receipt: Path) -> None:
    from pypdf import PdfReader

    report = {"status":"BLOCK","observed_file_sha256":{}, "yearbook":{}, "association":{}, "issuer_references":{}}
    sets = {}
    for key in URLS:
        path = folder/(key+".pdf")
        if path.is_file():
            report["observed_file_sha256"][key]=hashlib.sha256(path.read_bytes()).hexdigest()
    yearbook = folder/"yearbook.pdf"
    if yearbook.is_file() and report["observed_file_sha256"]["yearbook"]==YEARBOOK_SHA:
        reader=PdfReader(yearbook, strict=True)
        # Exact 2024 year-end summary row (visually/independently extracted
        # web text), not an imputation from the rank count.
        summary = []
        for i in range(16,40):
            txt=normalize_text(reader.pages[i].extract_text() or "")
            if ("LISTEDSECURITIES" in txt and "2017" in txt and "2024" in txt
                    and "1521" in txt and "1365" in txt and "2886" in txt):
                summary.append(i+1)
        report["yearbook_summary_anchor_pages"]=summary
        poppler=shutil.which("pdftotext")
        for board, start in START.items():
            rows, malformed=[], 0
            for i in range(start,start+TABLES[board][1]):
                parsed,bad=parse_rows(reader.pages[i].extract_text(extraction_mode="layout") or "")
                rows.extend(parsed)
                malformed+=bad
            out=summarize_rows(rows,board,malformed)
            out |= row_anomalies(rows,board)
            out["prior_rank_projection_match"]=out["ranked_code_projection_sha256"]==BOARD_HASH[board]
            out["poppler_projection_match"]=False
            if poppler:
                try:
                    result=subprocess.run([poppler,"-f",str(start+1),"-l",str(start+TABLES[board][1]),
                                           "-layout",str(yearbook),"-"], capture_output=True, timeout=18, check=True)
                    other,bad=parse_rows(result.stdout.decode("utf-8"))
                    out["poppler_rows"]=len(other)
                    out["poppler_malformed_rows"]=bad
                    out["poppler_projection_match"]=other==rows and bad==malformed
                    out["poppler_code_projection_match"]=[[r[0],r[1],r[2]] for r in other]==[[r[0],r[1],r[2]] for r in rows]
                except (OSError,ValueError,subprocess.SubprocessError) as exc:
                    out["poppler_error"]=type(exc).__name__
            report["yearbook"][board]=out
            sets[board]={r[1] for r in rows}
    for key in ("h1","h2"):
        path=folder/(key+".pdf")
        if path.is_file():
            try:
                sets[key], report["association"][key]=capco_parse(path,key)
            except (ValueError,TypeError,KeyError,RuntimeError,IndexError) as exc:
                report["association"][key]={"status":"BLOCK","reason":str(exc) if str(exc).startswith("CAPCO_") else type(exc).__name__}
    for key in ("h1_issuer","h2_issuer"):
        path=folder/(key+".pdf")
        if path.is_file():
            try:
                report["issuer_references"][key]=issuer_parse(path,key)
            except (ValueError,TypeError,KeyError,RuntimeError,IndexError) as exc:
                report["issuer_references"][key]={"status":"BLOCK","reason":str(exc) if str(exc).startswith("CAPCO_") else type(exc).__name__}
    comparisons={}
    if {"h1","h2"}<=sets.keys():
        comparisons["h1_vs_h2"]=compare_sets(sets["h1"],sets["h2"])
    if {"main","chinext","h2"}<=sets.keys():
        for board in ("main","chinext"):
            selected={c for c in sets["h2"] if c.startswith(TABLES[board][3])}
            comparisons[board+"_vs_h2"]=compare_sets(sets[board],selected)
    report["comparisons"]=comparisons
    report["historical_universe_complete"]=False
    report["pit_safe"]=False
    report["status"]="WARN" if (all(key in sets for key in ("main","chinext","h1","h2"))
        and all(v["status"]=="OBSERVED_CODE_SET_ONLY" for v in report["association"].values())
        and all(v["prior_rank_projection_match"] for v in report["yearbook"].values())
        and len(report["issuer_references"])==2
        and all(v["status"]=="OBSERVED_ISSUER_REPORTED_RELEASE_DAY" for v in report["issuer_references"].values())) else "BLOCK"
    write_worker_result(receipt,report)


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY")!=REPO:
        raise SystemExit("public repository required")
    report={"status":"BLOCK","executor_commit":os.environ["GITHUB_SHA"],"prior_yearbook_run":45939074990,
            "historical_universe_complete":False,"pit_safe":False,"decision_authority":False,
            "execution_allowed":False,"original_bodies_retained":False}
    with TemporaryDirectory() as temp:
        folder=Path(temp)
        receipts={}
        for key in URLS:
            _,receipts[key]=observe(key,folder)
        report["observations"]=receipts
        parser=run_json_worker((sys.executable,"-m","investment_evidence_engine.szse_factbook_reconcile",
                                "--parse",str(folder)),timeout_seconds=85,max_bytes=256*1024)
        report["parser_worker"]={"status":parser.status,"elapsed_seconds":parser.elapsed_seconds}
        if parser.status=="OK" and parser.payload is not None:
            parsed=parser.payload
            report["reconciliation"]=parsed
            expected={k:r["source_sha256"] for k,r in receipts.items() if r.get("parent_rehash")=="MATCH"}
            if parsed["observed_file_sha256"]==expected:
                report["parser_input_hashes_match"]=True
                report["status"]=parsed["status"]
    print("PUBLIC_SZSE_FACTBOOK_RECONCILE "+json.dumps(report,sort_keys=True,allow_nan=False),flush=True)
    return 0 if report["status"]=="WARN" else 2


if __name__=="__main__":
    if len(sys.argv)==5 and sys.argv[1]=="--fetch" and sys.argv[2] in URLS:
        fetch(sys.argv[2],Path(sys.argv[3]),Path(sys.argv[4]))
    elif len(sys.argv)==4 and sys.argv[1]=="--parse":
        parse_all(Path(sys.argv[2]),Path(sys.argv[3]))
    elif len(sys.argv)==1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
