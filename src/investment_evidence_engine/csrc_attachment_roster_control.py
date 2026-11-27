"""Fixed official CSRC XLSX attachments; retrospective issuer evidence only."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote, unquote, urljoin
from zipfile import ZipFile

from .bounded_worker import run_json_worker, write_worker_result

REPO = "riyuewuxing/InvestmentEvidenceEngine"
MODULE = "investment_evidence_engine.csrc_attachment_roster_control"
BASE = "https://www.csrc.gov.cn"
SOURCES = {
    "shanghai": ("/shanghai/c103855/c7530473", "1735854050000",
                 "上海辖区上市公司名录（截至2024.12.31）", "上海辖区上市公司名录（截至2024.12.31）.xlsx"),
    "shenzhen": ("/shenzhen/c104311/c7535610", "1737678646000",
                 "深圳辖区上市公司名录（2024年12月）", "深圳辖区上市公司名录2024年12月.xlsx"),
    "jiangxi": ("/jiangxi/c104159/c7532495", "1736447541000",
                "江西辖区上海证券交易所、深圳证券交易所上市公司名录（2024年12月）",
                "江西辖区上海证券交易所、深圳证券交易所上市公司名录（2024年12月）.xlsx"),
}
MAX_BYTES = 4 * 1024 * 1024
MAX_ZIP_EXPANDED = 20 * 1024 * 1024
HEADER_NAMES = {"证券代码", "股票代码", "公司代码", "上市代码"}
CODE = re.compile(r"[0-9]{6}(?:\.(?:SH|SZ|BJ))?")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.extend(v for k, v in attrs if k == "href" and v)


def fixed_urls(key: str) -> tuple[str, str]:
    path, _, _, filename = SOURCES[key]
    return BASE + path + "/content.shtml", BASE + path + "/" + path.rsplit("/", 1)[1].removeprefix("c") + "/files/" + quote(filename)


def bounded_fetch(url: str, deadline: float) -> bytes:
    import httpx

    with httpx.Client(timeout=httpx.Timeout(10), follow_redirects=False) as client:
        with client.stream("GET", url, headers={"Accept-Encoding": "identity"}) as response:
            response.raise_for_status()
            if str(response.url) != url:
                raise ValueError("source changed")
            buf = bytearray()
            for chunk in response.iter_bytes():
                if time.monotonic() > deadline or len(buf) + len(chunk) > MAX_BYTES:
                    raise ValueError("bounded transport limit")
                buf.extend(chunk)
            if not buf:
                raise ValueError("empty response")
            return bytes(buf)


def normalize_code(value, number_format: str) -> str | None:
    if isinstance(value, str):
        candidate = re.sub(r"\s+", "", value).upper()
    elif type(value) is int and 0 <= value <= 999999 and number_format == "000000":
        candidate = f"{value:06d}"
    elif type(value) is int and 100000 <= value <= 999999:
        candidate = str(value)
    else:
        return None
    return candidate if CODE.fullmatch(candidate) else None


def board_candidate(code: str) -> str:
    bare, _, suffix = code.partition(".")
    if bare.startswith(("600", "601", "603", "605")):
        inferred = "SH_MAIN"
    elif bare.startswith(("688", "689")):
        inferred = "SH_STAR"
    elif bare.startswith("900"):
        inferred = "SH_B"
    elif bare.startswith(("000", "001", "002", "003")):
        inferred = "SZ_MAIN"
    elif bare.startswith(("300", "301")):
        inferred = "SZ_CHINEXT"
    elif bare.startswith("200"):
        inferred = "SZ_B"
    elif bare.startswith(("4", "8", "920")):
        inferred = "BJ_CANDIDATE"
    else:
        inferred = "UNKNOWN"
    if suffix and not inferred.startswith(suffix):
        return "SUFFIX_CONFLICT"
    return inferred


def summarize_workbook(raw: bytes) -> dict:
    from openpyxl import load_workbook

    with ZipFile(io.BytesIO(raw)) as archive:
        files = archive.infolist()
        if len(files) > 256 or sum(x.file_size for x in files) > MAX_ZIP_EXPANDED:
            raise ValueError("expanded archive outside limit")
    book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True, keep_links=False)
    sheets = []
    code_sets = {}
    try:
        if len(book.worksheets) > 12:
            raise ValueError("too many worksheets")
        for index, sheet in enumerate(book.worksheets):
            if sheet.max_row is None or sheet.max_column is None or sheet.max_row > 5000 or sheet.max_column > 40:
                sheets.append({"index": index, "status": "BLOCK", "reason": "dimensions"})
                continue
            columns = []
            header_row = None
            codes = []
            rejected = 0
            numeric_unformatted = 0
            blank_code_nonempty = 0
            nonempty_rows = 0
            code_like_rows = 0
            summary_markers = set()
            for row_number, row in enumerate(sheet.iter_rows(), 1):
                nonempty_rows += int(any(cell.value is not None for cell in row))
                if header_row is None:
                    code_like_rows += int(any(normalize_code(cell.value, cell.number_format) is not None for cell in row))
                    for cell in row:
                        if isinstance(cell.value, str):
                            label = re.sub(r"\s+", "", cell.value)
                            for marker in ("上市公司数量", "上市公司数", "上市公司家数", "证券交易所", "上海证券交易所", "深圳证券交易所", "主板", "科创板", "创业板", "合计", "总计", "辖区", "统计"):
                                if marker in label:
                                    summary_markers.add(marker)
                if header_row is None:
                    if row_number > 15:
                        continue
                    columns = [i for i, c in enumerate(row) if isinstance(c.value, str)
                               and re.sub(r"\s+", "", c.value) in HEADER_NAMES]
                    if len(columns) == 1:
                        header_row = row_number
                    continue
                cell = row[columns[0]]
                if cell.value is None:
                    blank_code_nonempty += int(any(c.value is not None for c in row))
                    continue
                code = normalize_code(cell.value, cell.number_format)
                if code is None:
                    rejected += 1
                    numeric_unformatted += int(type(cell.value) is int)
                else:
                    codes.append(code)
            code_sets[index] = set(codes)
            candidate = Counter(board_candidate(c) for c in codes)
            bare_codes = [c.split(".")[0] for c in codes]
            sheets.append({"index": index, "header_row": header_row, "rows": len(codes), "nonempty_rows": nonempty_rows,
                           "unrecognized_header_code_like_rows": code_like_rows if header_row is None else None,
                           "unrecognized_header_summary_markers": sorted(summary_markers) if header_row is None else [],
                           "unique_codes": len(set(codes)), "unique_bare_codes": len(set(bare_codes)),
                           "rejected": rejected, "numeric_unformatted": numeric_unformatted,
                           "blank_code_nonempty": blank_code_nonempty,
                           "board_prefix_candidates_not_exchange_proof": dict(candidate),
                           "suffix_rows": sum("." in c for c in codes),
                           "code_set_sha256": digest(json.dumps(sorted(set(codes)), separators=(",", ":")).encode()),
                           "status": "EMPTY" if not nonempty_rows else ("WARN" if header_row and codes and not rejected and not blank_code_nonempty
                           and len(set(bare_codes)) == len(codes) and not candidate["SUFFIX_CONFLICT"] else "BLOCK")})
    finally:
        book.close()
    partition = {"checked": False}
    if len(sheets) == 4 and all(i in code_sets for i in (0, 2, 3)):
        total, sh, sz = (code_sets[i] for i in (0, 2, 3))
        partition = {"checked": True, "disjoint": not bool(sh & sz), "union_equals_total": (sh | sz) == total,
                     "sh_suffix_exact": bool(sh) and all(v.endswith(".SH") for v in sh),
                     "sz_suffix_exact": bool(sz) and all(v.endswith(".SZ") for v in sz)}
    usable = any(s["status"] == "WARN" for s in sheets) and all(s["status"] in ("WARN", "EMPTY") for s in sheets)
    if partition["checked"]:
        usable = usable and all(partition.values())
    return {"sheets": sheets, "partition_check": partition, "status": "WARN" if usable else "BLOCK",
            "regional_issuer_roster_only": True, "complete_historical_universe_verified": False,
            "pit_safe": False}


def worker(key: str, folder: Path, result: Path) -> None:
    page, attachment = fixed_urls(key)
    _, date, title, _ = SOURCES[key]
    started = datetime.now(UTC).isoformat()
    report = {"status": "BLOCK", "page_url": page, "attachment_url": attachment, "started_at": started}
    try:
        deadline = time.monotonic() + 45
        html_bytes = bounded_fetch(page, deadline)
        with (folder / "page.html").open("xb") as out:
            out.write(html_bytes)
        html = html_bytes.decode("utf-8")
        links = Links()
        links.feed(html)
        report.update(page_bytes=len(html_bytes), page_sha256=digest(html_bytes),
                      title_marker=title in html, date_marker=date in html,
                      exact_attachment_link=any(unquote(urljoin(page, v)) == unquote(attachment) for v in links.links))
        if not all(report[k] for k in ("title_marker", "date_marker", "exact_attachment_link")):
            raise ValueError("publisher linkage unavailable")
        report["publisher_reported_publication_utc"] = datetime.fromtimestamp(int(date)/1000, UTC).isoformat()
        raw = bounded_fetch(attachment, deadline)
        report.update(attachment_bytes=len(raw), attachment_sha256=digest(raw),
                      observed_at=datetime.now(UTC).isoformat())
        with (folder / "roster.xlsx").open("xb") as out:
            out.write(raw)
        report["workbook"] = summarize_workbook(raw)
        report["status"] = report["workbook"]["status"]
    except Exception as exc:
        report["error_type"] = type(exc).__name__
    write_worker_result(result, report)


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    observations = {}
    selected = ("jiangxi",) if os.environ.get("CSRC_JIANGXI_ONLY") == "1" else tuple(SOURCES)
    for key in selected:
        with TemporaryDirectory() as folder:
            result = run_json_worker((sys.executable, "-m", MODULE, "--observe", key, folder),
                                     timeout_seconds=60, max_bytes=65536)
            data = result.payload or {"status": "BLOCK"}
            data.update(worker_status=result.status, worker_elapsed_seconds=result.elapsed_seconds)
            for name, hash_key in (("page.html", "page_sha256"), ("roster.xlsx", "attachment_sha256")):
                target = Path(folder) / name
                data[name + "_parent_rehash"] = "MATCH" if target.is_file() and digest(target.read_bytes()) == data.get(hash_key) else "NOT_VERIFIED"
            if data["page.html_parent_rehash"] != "MATCH" or data["roster.xlsx_parent_rehash"] != "MATCH":
                data["status"] = "BLOCK"
            if selected == ("jiangxi",) and (data.get("page_sha256") != "b0e343022fd7edabe8ac56bf96aa5827a834e7e2161296ed19ce843a20e786e7" or data.get("attachment_sha256") != "a0133a28f6a3bcba3c3e056f29767f83436b8db1c6964cbd977924c99e6135c6"):
                data["status"] = "BLOCK"
                data["reason"] = "prior_version_mismatch"
            observations[key] = data
    status = "WARN" if any(x["status"] == "WARN" for x in observations.values()) else "BLOCK"
    report = {"status": status, "observations": observations, "as_of": "2024-12-31",
              "executor_commit": os.environ["GITHUB_SHA"], "raw_sources_retained": False,
              "historical_availability_verified": False, "pit_safe": False,
              "decision_authority": False, "execution_allowed": False}
    print("PUBLIC_CSRC_ATTACHMENT_ROSTERS " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if status == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--observe" and sys.argv[2] in SOURCES:
        worker(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
