"""Retrospective BSE year-end candidate reconciliation, not listing admission."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote

from .bounded_worker import run_json_worker, write_worker_result
from .official_pdf_transport import read_bounded_pdf

REPO = "riyuewuxing/InvestmentEvidenceEngine"
MODULE = "investment_evidence_engine.bse_2024_roster_reconciliation"
URLS = {
    "mapping": "https://capcofile.oss-cn-beijing.aliyuncs.com/2025/file/" + quote("附件：北交所存量上市公司股票新旧代码对照表.pdf"),
    "ipo": "https://pdf.dfcfw.com/pdf/H3_AP202501121641896845_1.pdf?1736711858000.pdf=",
}
CUTOFF = date(2024, 12, 31)
MAX_BYTES = 8 * 1024 * 1024
CQ_OLD = {"830896", "831370", "833873", "834033", "871857", "873833"}
PILOT = {"833819", "830799", "831445", "430489", "839167", "834682"}
MAPPING_ROW = re.compile(r"^\s*(\d{1,3})\s+.+?\s+(\d{4}-\d{2}-\d{2})\s+([48]\d{5})\s+(920\d{3})\s*$")
IPO_ROW = re.compile(r"^\s*(\d{1,2})\s+([489]\d{5})\s+.+?\s+(\d{4}/\d{1,2}/\d{1,2})\s+(\d{4}/\d{1,2}/\d{1,2})\s+(\d{4}/\d{1,2}/\d{1,2})\s*$")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse_mapping(text: str) -> list[tuple[int, str, str, str]]:
    rows = []
    for line in text.splitlines():
        match = MAPPING_ROW.fullmatch(line)
        if match:
            idx, day, old, new = match.groups()
            rows.append((int(idx), date.fromisoformat(day).isoformat(), old, new))
    return rows


def parse_ipo(text: str) -> list[tuple[int, str, str]]:
    rows = []
    for line in text.splitlines():
        match = IPO_ROW.fullmatch(line)
        if match:
            idx, code, _, _, listed = match.groups()
            year, month, day = map(int, listed.split("/"))
            rows.append((int(idx), code, date(year, month, day).isoformat()))
    return rows


def reconcile(mapping: list[tuple[int, str, str, str]], ipo: list[tuple[int, str, str]]) -> dict:
    old = {r[2] for r in mapping}
    new = {r[3] for r in mapping}
    listed2024 = {code: day for _, code, day in ipo if "2024-01-01" <= day <= CUTOFF.isoformat()}
    mapped2024 = {r[2]: r[1] for r in mapping if r[1].startswith("2024-")}
    native = {code for code in listed2024 if code.startswith("920")}
    old_ipo = {code: day for code, day in listed2024.items() if not code.startswith("920")}
    after = [(code, day) for _, code, day in ipo if day > CUTOFF.isoformat()]
    mapping_ok = (len(mapping) == len(old) == len(new) == 248
                  and [r[0] for r in mapping] == list(range(1, 249))
                  and all(r[1] < "2024-04-22" for r in mapping)
                  and PILOT <= old and ("837023", "920123") in {(r[2], r[3]) for r in mapping})
    ipo_ok = (len(ipo) == len({r[1] for r in ipo}) == 24
              and [r[0] for r in ipo] == list(range(1, 25))
              and len(listed2024) == 23 and after == [("920116", "2025-01-02")])
    candidate = old | native
    good = (mapping_ok and ipo_ok and mapped2024 == old_ipo and len(native) == 14
            and not (native & new) and len(candidate) == 262 and CQ_OLD <= old)
    return {
        "status": "WARN" if good else "BLOCK", "mapping_rows": len(mapping),
        "unique_old": len(old), "unique_new": len(new), "mapping_shape_matches": mapping_ok,
        "ipo_rows": len(ipo), "ipo_shape_matches": ipo_ok, "ipo_2024_count": len(listed2024),
        "old_ipo_count": len(old_ipo), "mapped_2024_count": len(mapped2024),
        "same_legacy_2024_code_date_set": mapped2024 == old_ipo and bool(mapped2024),
        "native_920_2024_count": len(native), "native_overlap_with_mapped_new": len(native & new),
        "after_cutoff_excluded": after,
        "cq_legacy_codes_matched": len(CQ_OLD & old),
        "candidate_2024_year_end_count": len(candidate), "expected_year_end_aggregate": 262,
        "candidate_matches_aggregate": len(candidate) == 262,
        "candidate_code_set_sha256": digest(json.dumps(sorted(candidate), separators=(",", ":")).encode()),
        "old_new_suffix_counterexamples": sum(r[2][-3:] != r[3][-3:] for r in mapping),
        "selected_layer_date_rows": sum(r[1] < "2021-11-15" for r in mapping),
        "mapping_later_publication": True, "ipo_report_later_publication": True,
        "complete_historical_universe_verified": False,
        "historical_availability_verified": False, "pit_safe": False}


def download(kind: str, target: Path, result: Path) -> None:
    import httpx

    started = datetime.now(UTC).isoformat()
    report = {"status": "BLOCK", "url": URLS[kind], "started_at": started}
    try:
        with httpx.Client(timeout=httpx.Timeout(10), follow_redirects=False) as client:
            with client.stream("GET", URLS[kind], headers={"Accept": "application/pdf", "Accept-Encoding": "identity"}) as response:
                if str(response.url) != URLS[kind]:
                    raise ValueError("source route changed")
                raw = read_bounded_pdf(response, time.monotonic() + 35, max_bytes=MAX_BYTES)
        with target.open("xb") as out:
            out.write(raw)
        report.update(status="OBSERVED", source_bytes=len(raw), source_sha256=digest(raw),
                      observed_at=datetime.now(UTC).isoformat())
    except Exception as exc:
        report.update(error_type=type(exc).__name__, http_status=getattr(getattr(exc, "response", None), "status_code", None))
    write_worker_result(result, report)


def parse(folder: Path, result: Path) -> None:
    from pypdf import PdfReader

    raw_map, raw_ipo = (folder / "mapping.pdf").read_bytes(), (folder / "ipo.pdf").read_bytes()
    r_map, r_ipo = PdfReader(folder / "mapping.pdf", strict=True), PdfReader(folder / "ipo.pdf", strict=True)
    report = {"status": "BLOCK", "mapping_input_sha256": digest(raw_map), "ipo_input_sha256": digest(raw_ipo),
              "mapping_pages": len(r_map.pages), "ipo_pages": len(r_ipo.pages)}
    if not 1 <= len(r_map.pages) <= 12 or len(r_ipo.pages) != 14 or r_map.is_encrypted or r_ipo.is_encrypted:
        write_worker_result(result, report | {"reason": "page_scope"})
        return
    mapping_text = "\n".join(p.extract_text(extraction_mode="layout") or "" for p in r_map.pages)
    ipo_text = "\n".join(r_ipo.pages[i].extract_text(extraction_mode="layout") or "" for i in (10, 11))
    map_marker = "北交所存量上市公司股票新旧代码对照表" in re.sub(r"\s+", "", mapping_text)
    ipo_marker = "20250112" in re.sub(r"\s+", "", r_ipo.pages[0].extract_text() or "")
    mapping, ipo = parse_mapping(mapping_text), parse_ipo(ipo_text)
    outcome = reconcile(mapping, ipo)
    report.update(mapping_marker=map_marker, ipo_report_date_marker=ipo_marker, reconciliation=outcome,
                  status=outcome["status"] if map_marker and ipo_marker else "BLOCK")
    write_worker_result(result, report)


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    report = {"status": "BLOCK", "as_of": CUTOFF.isoformat(), "executor_commit": os.environ["GITHUB_SHA"],
              "raw_sources_retained": False, "pit_safe": False, "decision_authority": False, "execution_allowed": False}
    with TemporaryDirectory() as directory:
        folder = Path(directory)
        sources = {}
        for kind in URLS:
            target = folder / (kind + ".pdf")
            task = run_json_worker((sys.executable, "-m", MODULE, "--download", kind, str(target)),
                                   timeout_seconds=45, max_bytes=65536)
            data = task.payload or {"status": "BLOCK"}
            data.update(worker_status=task.status, elapsed_seconds=task.elapsed_seconds)
            data["parent_rehash"] = "MATCH" if target.is_file() and digest(target.read_bytes()) == data.get("source_sha256") else "NOT_VERIFIED"
            sources[kind] = data
        report["sources"] = sources
        if all(d["status"] == "OBSERVED" and d["parent_rehash"] == "MATCH" for d in sources.values()):
            task = run_json_worker((sys.executable, "-m", MODULE, "--parse", str(folder)),
                                   timeout_seconds=45, max_bytes=65536)
            report.update(parser_worker=task.status, parser_elapsed_seconds=task.elapsed_seconds)
            if task.payload:
                report["parser"] = task.payload
                if all(task.payload.get(k + "_input_sha256") == sources[k]["source_sha256"] for k in URLS):
                    report["parser_rehash"] = "MATCH"
                    report["status"] = task.payload["status"]
    print("PUBLIC_BSE_2024_ROSTER " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--download" and sys.argv[2] in URLS:
        download(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))
    elif len(sys.argv) == 4 and sys.argv[1] == "--parse":
        parse(Path(sys.argv[2]), Path(sys.argv[3]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
