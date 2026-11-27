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
TAIL_URLS = {
    "month_counts": "https://docs.static.szse.cn/www/aboutus/research/secuities/daily/W020250108392800406412.pdf",
    "b_identity": "https://disc.static.szse.cn/disc/disk03/finalpage/2024-04-01/c52d1b92-4cac-4c22-bd59-b118c8a32d0e.PDF",
    "bailong_exit": "https://static.cninfo.com.cn/finalpage/2024-01-23/1218989547.PDF",
    "dongxu_exit": "https://static.cninfo.com.cn/finalpage/2024-10-11/1221359894.PDF",
}
AIDIER_URLS = {
    "aidier_decision": "https://disc.static.szse.cn/disc/disk03/finalpage/2024-02-08/8eac0c98-49b3-40f6-b64e-fcd2bea0025a.PDF",
    "aidier_exit": "https://pdf.dfcfw.com/pdf/H2_AN202403031625209596_1.pdf",
}
ORIGINAL_KEYS = tuple(URLS)
URLS.update(TAIL_URLS)
URLS.update(AIDIER_URLS)
URLS["market_overview"]="https://www.szse.cn/market/subject/P020241231627621196204.pdf"
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
        identity, code, idxs = "广东长青(集团)股份有限公司", "002616", (9,)
        text = "".join(normalize_text(reader.pages[i].extract_text() or "") for i in idxs)
        marks = ("2025年4月18日", "2024年下半年上市公司行业分类结果", "N77", "生态保护和环境治理业")
        date, docday, industry = "2025-04-18", "2025-08-30", "N77"
    identity_page = first if key=="h1_issuer" else normalize_text(reader.pages[6].extract_text() or "")
    if identity not in first or identity not in identity_page or code not in identity_page or not all(m in text for m in marks):
        raise ValueError("CAPCO_ISSUER_CITATION_FIELDS")
    return {"status":"OBSERVED_ISSUER_REPORTED_RELEASE_DAY","symbol":code,"issuer_reported_release_day":date,
            "issuer_document_day":docday,"industry_code":industry,"checked_pdf_pages":[i+1 for i in idxs],"identity_pdf_pages":[1] if key=="h1_issuer" else [1,7],
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


def counts_from_text(text: str) -> dict:
    """Read the domestic stock listing rows, never the earlier global table."""
    start = text.find("国内证券市场数据")
    if start < 0 or "2024年12月底" not in normalize_text(text[start:start+80]):
        raise ValueError("MONTH_COUNTS_TITLE")
    text = text[start:]
    result = {}
    for key, label in (("a", r"A\s*股\s*[\(（]只[\)）]"), ("b", r"B\s*股\s*[\(（]只[\)）]"),
                       ("total", r"合计\s*[\(（]只[\)）]"), ("company", r"上市公司数\s*[\(（]家[\)）]")):
        match = re.search(label + r"\s+((?:[0-9,]+\s+){7}[0-9,]+)(?![0-9,])", text)
        if match is None:
            raise ValueError("MONTH_COUNTS_ROW_" + key)
        result[key] = [int(v.replace(",", "")) for v in match.group(1).split()]
    a, b, total, company = (result[k] for k in ("a", "b", "total", "company"))
    for values in result.values():
        if values[0]!=values[1]+values[2] or values[3]!=values[4]+values[5] or values[7]!=values[0]+values[3]+values[6]:
            raise ValueError("MONTH_COUNTS_SCOPE_SUM")
    if [x+y for x,y in zip(a,b,strict=True)]!=total:
        raise ValueError("MONTH_COUNTS_SHARE_SUM")
    if min(company)<0:
        raise ValueError("MONTH_COUNTS_COMPANY")
    return {"scope":"SZSE_PUBLICATION_DOMESTIC_STOCK_COUNTS_2024_12",
            "columns":["SZ_total","SZ_main","SZ_chinext","SH_total","SH_main","SH_star","BSE","all"],
            "counts":result,"publication_issue":"2025-01","first_availability_verified":False,
            "member_identities_verified":False}


def tail_partition(rows: list[tuple], n: int, confirmed_b: str | None) -> dict:
    """Diagnostic partition, NOT an admitted correction of the publication."""
    first, tail = rows[:n], rows[n:]
    first_left, first_right = ({r[i] for r in first} for i in (1,2))
    tail_left, tail_right = ({r[i] for r in tail} for i in (1,2))
    def kinds(codes: set[str]) -> dict:
        return {"a":sum(c.startswith(("000","001","002","003")) for c in codes),
                "b":sum(c.startswith("200") or c==confirmed_b for c in codes),
                "unknown":sum(not c.startswith(("000","001","002","003","200")) and c!=confirmed_b for c in codes)}
    return {"first_rows":len(first),"tail_rows":len(tail),
            "first_rank_sequence_match":[r[0] for r in first]==list(range(1,n+1)),
            "first_unique_left":len(first_left),"first_unique_right":len(first_right),
            "first_sets_match":first_left==first_right,"first_left_class_counts":kinds(first_left),
            "first_right_class_counts":kinds(first_right),
            "first_descending":all(Decimal(a[3])>=Decimal(b[3]) and Decimal(a[4])>=Decimal(b[4])
                                   for a,b in zip(first[:-1],first[1:],strict=True)),
            "tail_only_left":sorted(tail_left-first_left),"tail_only_right":sorted(tail_right-first_right),
            "tail_repeat_left_count":len(tail_left&first_left),"tail_repeat_right_count":len(tail_right&first_right),
            "first_market_value_delta_million":str(sum((Decimal(r[3]) for r in first),Decimal(0))-TOTALS["main"]),
            "first_code_set_sha256":digest_projection(sorted(first_left)),
            "historical_member_admission":False,"official_correction_claimed":False}


def partition_reconciled(part: dict, n: int) -> bool:
    return (part["first_rows"]==part["first_unique_left"]==part["first_unique_right"]==n
            and part["first_sets_match"] and part["first_descending"] and part["first_rank_sequence_match"]
            and abs(Decimal(part["first_market_value_delta_million"]))<=Decimal("0.005")*(n+1))


def aidier_fields(first: str, key: str) -> dict:
    text=normalize_text(first)
    common=("福建省爱迪尔珠宝实业股份有限公司","002740","人民币普通股","2024年2月8日","126号")
    required=(("2024-019","关于收到股票终止上市决定的公告") if key=="aidier_decision"
              else ("2024-023","关于股票终止上市暨摘牌的公告","摘牌日期:2024年3月4日"))
    if not all(mark in text for mark in (*common,*required)):
        raise ValueError("AIDIER_ISSUER_FIELDS")
    return {"status":"OBSERVED_ISSUER_FIELDS","code":"002740","decision_day":"2024-02-08",
            "issuer_reported_delisting_day":"2024-03-04" if key=="aidier_exit" else None,
            "delivery":"ISSUER_PDF_ON_EXCHANGE" if key=="aidier_decision" else "ISSUER_PDF_ON_MEDIA_MIRROR",
            "first_availability_verified":False}


def parse_aidier(folder: Path, receipt: Path) -> None:
    from pypdf import PdfReader

    report={"status":"BLOCK","observed_file_sha256":{},"references":{},"pit_safe":False,
            "historical_universe_complete":False,"prior_tail_run":45939705961}
    for key in AIDIER_URLS:
        path=folder/(key+".pdf")
        if not path.is_file():
            continue
        report["observed_file_sha256"][key]=hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            reader=PdfReader(path,strict=True)
            if reader.is_encrypted or not 1<=len(reader.pages)<=10:
                raise ValueError("AIDIER_PAGE_SCOPE")
            report["references"][key]=aidier_fields(reader.pages[0].extract_text() or "",key)
        except (ValueError,TypeError,RuntimeError,IndexError) as exc:
            report["references"][key]={"status":"BLOCK","reason":str(exc) if str(exc).startswith("AIDIER_") else type(exc).__name__}
    if len(report["references"])==2 and all(v["status"]=="OBSERVED_ISSUER_FIELDS" for v in report["references"].values()):
        report["status"]="WARN"
    write_worker_result(receipt,report)


def overview_fields(pages: list[str]) -> dict:
    titles=("2024年深圳证券市场概况","2024年主板市场概况","2024年创业板市场概况")
    if len(pages)!=3:
        raise ValueError("OVERVIEW_PAGE_SCOPE")
    counts=[]
    values=[]
    for page,title in zip(pages,titles,strict=True):
        flat=normalize_text(page)
        if title not in flat or "截至2024.12.31" not in flat:
            raise ValueError("OVERVIEW_TITLE_DATE")
        count=re.search(r"上市公司数\s+([0-9,]+)\s",page)
        value=re.search(r"总市值\s*[（(]亿元[）)]\s+([0-9,.]+)\s",page)
        if count is None or value is None:
            raise ValueError("OVERVIEW_FIELD_SCOPE")
        counts.append(int(count[1].replace(",","")))
        values.append(Decimal(value[1].replace(",","")))
    if counts[0]!=counts[1]+counts[2] or abs(values[0]-values[1]-values[2])>Decimal("0.015"):
        raise ValueError("OVERVIEW_TOTAL_MISMATCH")
    if any(abs(values[i+1]-TOTALS[b]/100)>Decimal("0.005") for i,b in enumerate(("main","chinext"))):
        raise ValueError("OVERVIEW_YEARBOOK_VALUE_MISMATCH")
    monthly=[2851,1486,1365]  # Observed independent monthly document, run 45939705961.
    return {"status":"OBSERVED_AGGREGATES_ONLY","as_of_date":"2024-12-31",
            "columns":["SZ_total","SZ_main","SZ_chinext"],"listed_company_counts":counts,
            "monthly_company_counts_reference":monthly,"monthly_source_run":45939705961,
            "company_count_differences":[x-y for x,y in zip(counts,monthly,strict=True)],
            "market_values_100m_cny":[str(v) for v in values],
            "market_values_match_yearbook_within_rounding":True,
            "company_count_difference_cause_verified":False,
            "member_identities_verified":False,"first_availability_verified":False}


def parse_overview(folder: Path, receipt: Path) -> None:
    from pypdf import PdfReader

    path=folder/"market_overview.pdf"
    report={"status":"BLOCK","observed_file_sha256":{},"pit_safe":False,
            "historical_universe_complete":False}
    if path.is_file():
        report["observed_file_sha256"]["market_overview"]=hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            reader=PdfReader(path,strict=True)
            if reader.is_encrypted or len(reader.pages)!=3:
                raise ValueError("OVERVIEW_PAGE_SCOPE")
            report["overview"]=overview_fields([p.extract_text(extraction_mode="layout") or "" for p in reader.pages])
            report["status"]="WARN"
        except (ValueError,TypeError,RuntimeError,IndexError) as exc:
            report["reason"]=str(exc) if str(exc).startswith("OVERVIEW_") else type(exc).__name__
    write_worker_result(receipt,report)


def parse_tail(folder: Path, receipt: Path) -> None:
    from pypdf import PdfReader

    report={"status":"BLOCK","observed_file_sha256":{},"references":{},"historical_universe_complete":False,
            "pit_safe":False}
    for key in ("yearbook", *TAIL_URLS):
        path=folder/(key+".pdf")
        if path.is_file():
            report["observed_file_sha256"][key]=hashlib.sha256(path.read_bytes()).hexdigest()
    for key in TAIL_URLS:
        path=folder/(key+".pdf")
        if not path.is_file():
            continue
        try:
            reader=PdfReader(path,strict=True)
            if reader.is_encrypted or not 1<=len(reader.pages)<=20:
                raise ValueError("TAIL_REFERENCE_PAGE_SCOPE")
            if key=="month_counts":
                item=counts_from_text(reader.pages[1].extract_text(extraction_mode="layout") or "")
                report["references"][key]=item
                continue
            flat="".join(normalize_text(page.extract_text() or "") for page in reader.pages[:3])
            if key=="b_identity":
                marks=("招商局港口集团股份有限公司","001872/201872","招港B","深圳证券交易所")
                fields={"a_code":"001872","b_code":"201872","issuer_document_day":"2024-04-01"}
            elif key=="bailong_exit":
                marks=("广东柏堡龙股份有限公司","002776","摘牌日期:2024年1月25日","终止上市决定日期:2024年1月19日")
                fields={"codes":["002776"],"issuer_reported_delisting_day":"2024-01-25"}
            else:
                marks=("东旭光电科技股份有限公司","000413","200413","摘牌日期:2024年10月11日","2024年9月20日")
                fields={"codes":["000413","200413"],"issuer_reported_delisting_day":"2024-10-11"}
            if not all(m in flat for m in marks):
                raise ValueError("TAIL_REFERENCE_FIELDS")
            report["references"][key]={"status":"OBSERVED_ISSUER_FIELDS",**fields,"first_availability_verified":False}
        except (ValueError,TypeError,KeyError,RuntimeError,IndexError) as exc:
            report["references"][key]={"status":"BLOCK","reason":str(exc) if str(exc).startswith(("TAIL_","MONTH_")) else type(exc).__name__}
    if report["observed_file_sha256"].get("yearbook")==YEARBOOK_SHA:
        reader=PdfReader(folder/"yearbook.pdf",strict=True)
        rows=[]
        malformed=0
        for i in range(START["main"],START["main"]+TABLES["main"][1]):
            parsed,bad=parse_rows(reader.pages[i].extract_text(extraction_mode="layout") or "")
            rows.extend(parsed)
            malformed+=bad
        projection=summarize_rows(rows,"main",malformed)
        report["prior_rank_projection_match"]=projection["ranked_code_projection_sha256"]==BOARD_HASH["main"]
        if report["prior_rank_projection_match"] and not malformed:
            ref=report["references"]
            bcode="201872" if ref.get("b_identity",{}).get("status")=="OBSERVED_ISSUER_FIELDS" else None
            part=tail_partition(rows,TABLES["main"][2],bcode)
            report["partition"]=part
            listed=ref.get("month_counts",{}).get("counts")
            if listed:
                report["first_partition_counts_match_month"]=(part["first_left_class_counts"]==part["first_right_class_counts"]==
                    {"a":listed["a"][1],"b":listed["b"][1],"unknown":0})
            exit_codes={c for key in ("bailong_exit","dongxu_exit")
                        for c in ref.get(key,{}).get("codes",[])}
            report["tail_only_issuer_reported_exit_codes"]=sorted((set(part["tail_only_left"])|set(part["tail_only_right"]))&exit_codes)
            report["unexplained_tail_only_codes"]=sorted((set(part["tail_only_left"])|set(part["tail_only_right"]))-exit_codes)
    if (report.get("prior_rank_projection_match") and report.get("first_partition_counts_match_month")
            and partition_reconciled(report["partition"],TABLES["main"][2])
            and len(report["references"])==4
            and all(v.get("status")=="OBSERVED_ISSUER_FIELDS" for k,v in report["references"].items() if k!="month_counts")):
        report["status"]="WARN"
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
        mode = os.environ.get("SZSE_RECONCILE_MODE", "")
        keys = ("h2_issuer",) if mode=="H2_ISSUER_ONLY" else ORIGINAL_KEYS
        if mode=="COUNTS_AND_TAIL":
            keys=("yearbook", *TAIL_URLS)
        elif mode=="AIDIER_ONLY":
            keys=tuple(AIDIER_URLS)
        elif mode=="MARKET_OVERVIEW_ONLY":
            keys=("market_overview",)
        for key in keys:
            _,receipts[key]=observe(key,folder)
        report["observations"]=receipts
        parser=run_json_worker((sys.executable,"-m","investment_evidence_engine.szse_factbook_reconcile",
                                "--parse-tail" if mode=="COUNTS_AND_TAIL" else "--parse-aidier" if mode=="AIDIER_ONLY" else "--parse-overview" if mode=="MARKET_OVERVIEW_ONLY" else "--parse",str(folder)),timeout_seconds=85,max_bytes=256*1024)
        report["parser_worker"]={"status":parser.status,"elapsed_seconds":parser.elapsed_seconds}
        if parser.status=="OK" and parser.payload is not None:
            parsed=parser.payload
            report["reconciliation"]=parsed
            expected={k:r["source_sha256"] for k,r in receipts.items() if r.get("parent_rehash")=="MATCH"}
            if parsed["observed_file_sha256"]==expected:
                report["parser_input_hashes_match"]=True
                report["status"]=parsed["status"]
                if os.environ.get("SZSE_RECONCILE_MODE")=="H2_ISSUER_ONLY":
                    report["scope"]="H2_ISSUER_FIELD_CORRECTION_ONLY"
                    report["prior_reconciliation_run"]=45939309237
                    ref=parsed["issuer_references"].get("h2_issuer",{})
                    report["status"]="WARN" if (ref.get("status")=="OBSERVED_ISSUER_REPORTED_RELEASE_DAY" and expected.get("h2_issuer")=="18ffd2d4649bc66ccfed61072954db08b22458ed349b6dcb5d47d5c491f53a60") else "BLOCK"
    print("PUBLIC_SZSE_FACTBOOK_RECONCILE "+json.dumps(report,sort_keys=True,allow_nan=False),flush=True)
    return 0 if report["status"]=="WARN" else 2


if __name__=="__main__":
    if len(sys.argv)==5 and sys.argv[1]=="--fetch" and sys.argv[2] in URLS:
        fetch(sys.argv[2],Path(sys.argv[3]),Path(sys.argv[4]))
    elif len(sys.argv)==4 and sys.argv[1]=="--parse":
        parse_all(Path(sys.argv[2]),Path(sys.argv[3]))
    elif len(sys.argv)==4 and sys.argv[1]=="--parse-tail":
        parse_tail(Path(sys.argv[2]),Path(sys.argv[3]))
    elif len(sys.argv)==4 and sys.argv[1]=="--parse-aidier":
        parse_aidier(Path(sys.argv[2]),Path(sys.argv[3]))
    elif len(sys.argv)==4 and sys.argv[1]=="--parse-overview":
        parse_overview(Path(sys.argv[2]),Path(sys.argv[3]))
    elif len(sys.argv)==1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
