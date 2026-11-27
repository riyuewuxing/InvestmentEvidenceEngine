"""Fixed SSE 2025-volume retrospective roster diagnostic; not PIT admission."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from .bounded_worker import run_json_worker, write_worker_result
from .exchange_listing import _listing_day
from .official_pdf_transport import read_bounded_pdf
from .snapshot_integrity import strict_json_loads

URL = "https://www.sse.com.cn/aboutus/publication/yearly/documents/c/10801255/files/02acb566841a48f0b2ca8941c73f4541.pdf"
REPO = "riyuewuxing/InvestmentEvidenceEngine"
EXPECTED_LENGTH = 37592482
EXPECTED_SHA256 = "6e50e1fef5fa4c77e72e9cf0f58c2318604041b34e9d2e94a0f5be2f56983dc9"
PRIOR_DIRECTORY_SHA256 = "d5e5dec58882aef4aba8be707087e9c3483ee1be9c2d1fcb6070e1ae9abc8990"
REMOVED_A = {"600112", "600213", "600220", "600277", "600290", "600297", "600306", "600321", "600565", "600647", "600766", "600823", "600836", "603133", "603555", "603603"}
REMOVED_B = {"900953"}
MAX_BYTES = 40 * 1024 * 1024
EXPECTED = {"main_a": 1693, "star": 581, "main_b": 43}
CODE = re.compile(r"^\s*(6[0-9]{5}|900[0-9]{3})\s+")
NUMBER = r"(?:[0-9]+(?:,[0-9]{3})*\.[0-9]{2}|[—–-])"
ROW = re.compile(r"^\s*(6[0-9]{5}|900[0-9]{3})\s+\S.{0,60}?\s+(" + NUMBER + r")\s+(" + NUMBER + r")\s+(" + NUMBER + r")\s+(" + NUMBER + r")\s+")
MODULE = "investment_evidence_engine.sse_factbook_control"


def board(code: str) -> str:
    if code.startswith(("688", "689")):
        return "star"
    if code.startswith(("600", "601", "603", "605")):
        return "main_a"
    if code.startswith("900"):
        return "main_b"
    return "unknown"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_rows(text: str) -> tuple[list[tuple[str, str]], int]:
    rows = []
    malformed = 0
    for line in text.splitlines():
        if not CODE.match(line):
            continue
        line = re.sub(r"(?<=\.)\s+(?=[0-9])", "", line)
        match = ROW.match(line)
        if match is None:
            malformed += 1
            continue
        rows.append((match[1], match[2].replace(",", "")))
    return rows, malformed


def summarize(rows: list[tuple[str, str]], malformed: int) -> dict:
    counts = Counter(code for code, _ in rows)
    output = {}
    for name, expected in EXPECTED.items():
        subset = [(c, v) for c, v in rows if board(c) == name]
        unique = sorted({c for c, _ in subset})
        positive = sorted({c for c, v in subset if v not in {"—", "–", "-"} and Decimal(v) > 0})
        nonpositive = sorted(set(unique) - set(positive))
        output[name] = {
            "rows": len(subset), "unique": len(unique), "expected_year_end": expected,
            "positive_market_value_codes": len(positive),
            "unique_count_matches": len(unique) == expected,
            "positive_count_matches": len(positive) == expected,
            "nonpositive_code_count": len(nonpositive),
            "nonpositive_codes": nonpositive[:40],
            "duplicate_codes": [c for c in unique if counts[c] > 1][:40],
            "code_set_sha256": digest(json.dumps(unique, separators=(",", ":")).encode()),
            "positive_code_set_sha256": digest(json.dumps(positive, separators=(",", ":")).encode()),
            "market_value_numeric_sum_million": str(sum((Decimal(v) for _, v in subset
                if v not in {"—", "–", "-"}), Decimal(0))),
        }
    unknown = sum(board(c) == "unknown" for c, _ in rows)
    return {"boards": output, "malformed": malformed, "unknown_board_rows": unknown,
            "unique_codes": len(counts), "rows": len(rows),
            "duplicate_code_count": sum(n > 1 for n in counts.values()),
            "complete_historical_universe_verified": False,
            "pit_safe": False}


def candidate_membership(rows: list[tuple[str, str]], company_codes: list[str]) -> dict:
    removed = REMOVED_A | REMOVED_B
    codes = {c for c, _ in rows}
    company_a = {c for c in company_codes if board(c) in {"main_a", "star"}}
    remaining = [(c, v) for c, v in rows if c not in removed]
    candidate = {c for c, _ in remaining}
    candidate_a = {c for c in candidate if board(c) in {"main_a", "star"}}
    sum_cap = sum((Decimal(v) for _, v in remaining if v not in {"—", "–", "-"}), Decimal(0))
    excluded_cap = sum((Decimal(v) for c, v in rows if c in removed and v not in {"—", "–", "-"}), Decimal(0))
    counts = Counter(board(c) for c in candidate)
    cdr = sorted(c for c in candidate if c.startswith("689"))
    good = (len(rows) == len(codes) and removed <= codes and candidate_a == company_a
            and counts == EXPECTED and len(cdr) == 1 and cdr == ["689009"])
    return {"status": "WARN" if good else "BLOCK", "excluded_codes_present": sorted(removed & codes),
            "candidate_counts": dict(counts), "candidate_total": len(candidate),
            "candidate_a_including_cdr": len(candidate_a), "candidate_cdr_codes": cdr,
            "ordinary_a_candidate_count": len(candidate_a) - len(cdr),
            "same_company_a_set": candidate_a == company_a and bool(company_a),
            "candidate_hash": digest(json.dumps(sorted(candidate), separators=(",", ":")).encode()),
            "candidate_market_value_sum_million": str(sum_cap),
            "excluded_market_value_sum_million": str(excluded_cap),
            "yearbook_reported_total_market_value_million": "52430899",
            "difference_million": str(sum_cap - Decimal("52430899")),
            "complete_historical_universe_verified": False, "pit_safe": False}


def directory_crosscheck(raw: bytes) -> dict:
    obj = strict_json_loads(raw)
    rows = obj.get("result")
    if not isinstance(rows, list) or len(rows) != obj.get("pageHelp", {}).get("total") and str(len(rows)) != str(obj.get("pageHelp", {}).get("total")):
        raise ValueError("directory incomplete")
    matched = {}
    targets = REMOVED_A | REMOVED_B
    for code in sorted(targets):
        field = "A_STOCK_CODE" if code in REMOVED_A else "B_STOCK_CODE"
        hits = [r for r in rows if r.get("COMPANY_CODE") == code or r.get(field) == code]
        if len(hits) != 1:
            matched[code] = {"status": "BLOCK", "hits": len(hits)}
            continue
        row = hits[0]
        value = row.get(field)
        removed = row.get("DELIST_DATE")
        exact = (value == code or value in (None, "", "-") and row.get("COMPANY_CODE") == code)
        try:
            parsed = _listing_day(removed)
            day = parsed.isoformat()
            year_match = parsed.year == 2024
        except (ValueError, TypeError, OverflowError):
            day = None
            year_match = False
        matched[code] = {"status": "MATCH" if exact and year_match else "BLOCK",
                         "identity_basis": field if value == code else "COMPANY_CODE_ONLY",
                         "directory_end_date": day if year_match else None}
    count = sum(v["status"] == "MATCH" for v in matched.values())
    return {"status": "WARN" if count == len(targets) else "BLOCK",
            "matched_count": count, "targets": matched,
            "directory_total": len(rows), "retrospective_only": True,
            "directory_date_semantics_not_full_trade_eligibility": True}


def observe_directory() -> dict:
    task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.delisting_directory",
                            "--child", "sse_delisted"), timeout_seconds=30, max_bytes=6 * 1024 * 1024)
    report = {"status": "BLOCK", "worker_status": task.status, "elapsed_seconds": task.elapsed_seconds}
    try:
        if not task.payload or "error" in task.payload:
            return report | {"error": (task.payload or {}).get("error")}
        p = task.payload
        raw = base64.b64decode(p["body"], validate=True)
        actual = digest(raw)
        from .delisting_directory import endpoint

        if actual != p["sha256"] or p["url"] != endpoint("sse_delisted")[0]:
            raise ValueError("source receipt mismatch")
        report.update(source_sha256=actual, source_bytes=len(raw), observed_at=p["observed"],
                      parent_rehash="MATCH", same_prior_directory_version=actual == PRIOR_DIRECTORY_SHA256)
        report.update(directory_crosscheck(raw))
    except Exception as exc:
        report["error_type"] = type(exc).__name__
    return report


def download(target: Path, result: Path) -> None:
    import httpx

    started = datetime.now(UTC).isoformat()
    try:
        with httpx.Client(timeout=httpx.Timeout(12), follow_redirects=False) as client:
            with client.stream("GET", URL, headers={"Accept": "application/pdf",
                                                    "Accept-Encoding": "identity"}) as response:
                if str(response.url) != URL:
                    raise ValueError("source scope changed")
                raw = read_bounded_pdf(response, time.monotonic() + 50, max_bytes=MAX_BYTES)
        info = {"source_bytes": len(raw), "source_sha256": digest(raw),
                "started_at": started, "observed_at": datetime.now(UTC).isoformat()}
        if len(raw) != EXPECTED_LENGTH or digest(raw) != EXPECTED_SHA256:
            write_worker_result(result, info | {"status": "BLOCK", "reason": "source_version_changed"})
            return
        with target.open("xb") as handle:
            handle.write(raw)
        write_worker_result(result, info | {"status": "OBSERVED"})
    except (OSError, ValueError, httpx.HTTPError) as exc:
        write_worker_result(result, {"status": "BLOCK", "error_type": type(exc).__name__,
                                    "started_at": started, "observed_at": datetime.now(UTC).isoformat()})


def parse(target: Path, result: Path) -> None:
    from pypdf import PdfReader

    sha = digest(target.read_bytes())
    reader = PdfReader(target, strict=True)
    report = {"status": "BLOCK", "source_sha256": sha, "pages": len(reader.pages)}
    if reader.is_encrypted or not 140 <= len(reader.pages) <= 1100:
        write_worker_result(result, report | {"reason": "page_scope"})
        return
    opening = "".join(reader.pages[i].extract_text() or "" for i in range(12))
    compact = re.sub(r"\s+", "", opening)
    report["edition_marker"] = "2025" in compact and "上海证券交易所统计年鉴" in compact
    report["edition_diagnostics"] = {"year": "2025" in compact, "title": "上海证券交易所统计年鉴" in compact, "english_title": "SHANGHAISTOCKEXCHANGESTATISTICSANNUAL" in compact.upper()}
    report["period_marker"] = "2024年1月1日至12月31日" in compact
    rows = []
    malformed = 0
    page_receipts = []
    diagnostic_shapes = []
    candidate_codes = []
    page_title_marker = False
    # Printed pp24-128 lie inside this bounded physical-page search window.
    for i in range(18, min(145, len(reader.pages))):
        text = reader.pages[i].extract_text(extraction_mode="layout") or ""
        normalized = re.sub(r"\s+", "", text).lower()
        if "股票代码" not in normalized or "市价总值" not in normalized or "本年最低" not in normalized:
            continue
        page_title_marker |= "上海证券交易所统计年鉴" in normalized
        candidate_codes.extend(m[1] for line in text.splitlines() if (m := CODE.match(line)))
        parsed, bad = parse_rows(text)
        if len(diagnostic_shapes) < 6:
            for line in text.splitlines():
                if CODE.match(line) and len(diagnostic_shapes) < 6:
                    diagnostic_shapes.append(re.sub(r"[^0-9.,\s—–-]", "X", line)[:300])
        if parsed or bad:
            page_receipts.append([i, len(parsed), bad, digest(text.encode())])
            rows.extend(parsed)
            malformed += bad
    report["edition_diagnostics"]["page_title"] = page_title_marker
    report["edition_marker"] = report["edition_diagnostics"]["year"] and (report["edition_diagnostics"]["title"] or page_title_marker)
    report["candidate_code_count"] = len(candidate_codes)
    report["candidate_unique_codes"] = len(set(candidate_codes))
    report["candidate_board_counts"] = dict(Counter(board(c) for c in candidate_codes))
    report["unparsed_codes"] = sorted(set(candidate_codes) - {code for code, _ in rows})[:80]
    company_codes = []
    company_pages = []
    for i in range(680, min(740, len(reader.pages))):
        text = reader.pages[i].extract_text(extraction_mode="layout") or ""
        normalized = re.sub(r"\s+", "", text).lower()
        if "公司代码" not in normalized or "总股本" not in normalized or "注册地" not in normalized:
            continue
        codes = [m[1] for line in text.splitlines() if (m := CODE.match(line))]
        if codes:
            company_pages.append([i, len(codes), digest(text.encode())])
            company_codes.extend(codes)
    company_a = {c for c in company_codes if board(c) in {"main_a", "star"}}
    trading_a = {c for c, v in rows if board(c) in {"main_a", "star"} and v not in {"—", "–", "-"} and Decimal(v) > 0}
    report["company_section"] = {"pages": company_pages, "rows": len(company_codes), "unique": len(set(company_codes)), "board_counts": dict(Counter(board(c) for c in company_codes)), "a_code_set_sha256": digest(json.dumps(sorted(company_a), separators=(",", ":")).encode()), "trading_only_a": sorted(trading_a - company_a)[:80], "company_only_a": sorted(company_a - trading_a)[:80], "same_positive_a_set": company_a == trading_a and bool(company_a), "trading_only_count": len(trading_a - company_a), "company_only_count": len(company_a - trading_a)}
    report["year_end_candidate"] = candidate_membership(rows, company_codes)
    report["selected_pages"] = page_receipts
    report["diagnostic_shapes"] = diagnostic_shapes
    report["roster"] = summarize(rows, malformed)
    report["status"] = "WARN" if rows and report["edition_marker"] and report["period_marker"] else "BLOCK"
    write_worker_result(result, report)


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    report = {"status": "BLOCK", "executor_commit": os.environ["GITHUB_SHA"],
              "url": URL, "statistical_as_of": "2024-12-31",
              "available_at_year_end_verified": False, "raw_pdf_retained": False,
              "decision_authority": False, "execution_allowed": False, "pit_safe": False}
    with TemporaryDirectory() as directory:
        target = Path(directory) / "sse.pdf"
        task = run_json_worker((sys.executable, "-m", MODULE, "--download", str(target)),
                               timeout_seconds=70, max_bytes=65536)
        report["download_worker"] = {"status": task.status, "elapsed_seconds": task.elapsed_seconds}
        if task.payload:
            report["download"] = task.payload
            if task.payload.get("status") == "OBSERVED" and target.is_file():
                raw = target.read_bytes()
                sha = digest(raw)
                if len(raw) == EXPECTED_LENGTH and sha == task.payload.get("source_sha256"):
                    report["parent_rehash"] = "MATCH"
                    parsed = run_json_worker((sys.executable, "-m", MODULE, "--parse", str(target)),
                                             timeout_seconds=90, max_bytes=128 * 1024)
                    report["parser_worker"] = {"status": parsed.status,
                                               "elapsed_seconds": parsed.elapsed_seconds}
                    if parsed.payload:
                        report["parser"] = parsed.payload
                        if parsed.payload.get("source_sha256") == sha:
                            report["parser_input_rehash"] = "MATCH"
                            report["status"] = parsed.payload["status"]
    report["directory_crosscheck"] = observe_directory()
    if report.get("parser", {}).get("year_end_candidate", {}).get("status") != "WARN" or report["directory_crosscheck"]["status"] != "WARN":
        report["status"] = "BLOCK"
    print("PUBLIC_SSE_FACTBOOK " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--download":
        download(Path(sys.argv[2]), Path(sys.argv[3]))
    elif len(sys.argv) == 4 and sys.argv[1] == "--parse":
        parse(Path(sys.argv[2]), Path(sys.argv[3]))
    elif sys.argv[1:] == ["--directory-only"]:
        if os.environ.get("GITHUB_REPOSITORY") != REPO:
            raise SystemExit("public repository required")
        report = observe_directory()
        print("PUBLIC_SSE_DIRECTORY_TARGETS " + json.dumps({"executor_commit": os.environ["GITHUB_SHA"], "directory": report, "pit_safe": False, "decision_authority": False}, sort_keys=True), flush=True)
        raise SystemExit(0 if report["status"] == "WARN" else 2)
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
