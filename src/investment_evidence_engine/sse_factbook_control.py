"""Fixed SSE 2025-volume retrospective roster diagnostic; not PIT admission."""
from __future__ import annotations

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
from .official_pdf_transport import read_bounded_pdf

URL = "https://www.sse.com.cn/aboutus/publication/yearly/documents/c/10801255/files/02acb566841a48f0b2ca8941c73f4541.pdf"
REPO = "riyuewuxing/InvestmentEvidenceEngine"
EXPECTED_LENGTH = 37592482
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
        if len(raw) != EXPECTED_LENGTH:
            write_worker_result(result, info | {"status": "BLOCK", "reason": "length_changed"})
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
    # Printed pp24-128 lie inside this bounded physical-page search window.
    for i in range(18, min(145, len(reader.pages))):
        text = reader.pages[i].extract_text(extraction_mode="layout") or ""
        normalized = re.sub(r"\s+", "", text).lower()
        if "股票代码" not in normalized or "市价总值" not in normalized or "本年最低" not in normalized:
            continue
        parsed, bad = parse_rows(text)
        if len(diagnostic_shapes) < 6:
            for line in text.splitlines():
                if CODE.match(line) and len(diagnostic_shapes) < 6:
                    diagnostic_shapes.append(re.sub(r"[^0-9.,\\s—–-]", "X", line)[:300])
        if parsed or bad:
            page_receipts.append([i, len(parsed), bad, digest(text.encode())])
            rows.extend(parsed)
            malformed += bad
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
    print("PUBLIC_SSE_FACTBOOK " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--download":
        download(Path(sys.argv[2]), Path(sys.argv[3]))
    elif len(sys.argv) == 4 and sys.argv[1] == "--parse":
        parse(Path(sys.argv[2]), Path(sys.argv[3]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
