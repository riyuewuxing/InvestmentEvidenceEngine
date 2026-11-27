"""Fixed issuer relisting notice: opening reference provenance and share reconciliation.

Read selected pages of the complete exchange-filed PDF. A disclosed opening
reference is not an actual opening price, fill, ordinary prior SSE close or
evidence of a specific investor's restored holdings. No raw body retention.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sys
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from tempfile import TemporaryDirectory

from .bounded_worker import run_json_worker, write_worker_result
from .official_pdf_transport import retrieve_pdf_bytes, validate_pdf_shape
from .public_symbol_change_control import compact

REPO = "riyuewuxing/InvestmentEvidenceEngine"
URL = "https://static.cninfo.com.cn/finalpage/2018-12-28/1205696113.PDF"
MAX_BYTES = 4 * 1024 * 1024
PAGES = (0, 1, 18, 19)


def parse_notice(pages: tuple[str, ...]) -> dict:
    if len(pages) != len(PAGES):
        raise ValueError("RELIST_ISSUER_PAGE_SCOPE")
    first, second, rules, last = map(compact, pages)
    anchors = (
        (first, ("证券代码:601975", "临2018-089", "关于公司股票重新上市的公告",
                 "2019年1月8日", "重新上市首日,公司股票价格不设涨跌幅限制",
                 "最后交易日(2017年2月27日)的收盘价,即4.31元/股",
                 "重新上市次日起,公司股票价格的日涨跌幅限制为5%")),
        (second, ("无限售条件流通股", "有限售条件流通股", "总股本")),
        (rules, ("最后交易日(2017年2月27日)的收盘价,即4.31元/股",
                 "首日不设涨跌幅限制")),
        (last, ("中国长江航运集团南京油运股份有限公司", "董事会")),
    )
    if any(not all(term in page for term in terms) for page, terms in anchors):
        raise ValueError("RELIST_ISSUER_ANCHOR_MISMATCH")
    # Accept exact reviewed rows, not an unconstrained number search.
    found = re.search(r"无限售条件流通股([0-9,]+)37\.79有限售条件流通股([0-9,]+)62\.21总股本([0-9,]+)100\.00", second)
    if found is None:
        raise ValueError("RELIST_ISSUER_SHARE_TABLE")
    free, restricted, total = (int(x.replace(",", "")) for x in found.groups())
    if (free, restricted, total) != (1898551957, 3124848067, 5023400024) or free + restricted != total:
        raise ValueError("RELIST_ISSUER_SHARE_RECONCILIATION")
    pct = lambda qty: str((Decimal(qty) * 100 / Decimal(total)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP))
    if (pct(free), pct(restricted)) != ("37.79", "62.21"):
        raise ValueError("RELIST_ISSUER_SHARE_PERCENT")
    # Date of signature is not the date in the archive URL or first public availability.
    signature_observed = any(term in last for term in ("二〇一八年十二月十八日", "二○一八年十二月十八日", "二0一八年十二月十八日"))
    return {
        "announcement_number": "临2018-089", "new_code": "601975",
        "relisting_session": "2019-01-08", "opening_reference_cny": "4.31",
        "opening_reference_source": "ISSUER_REPORTED_LAST_OTC_CLOSE",
        "opening_reference_source_session": "2017-02-27",
        "opening_reference_is_executed_open": False,
        "first_session_daily_limit": "NONE", "next_session_declared_limit_pct": 5,
        "total_shares": total, "unrestricted_shares": free, "restricted_shares": restricted,
        "unrestricted_share_pct_rounded": pct(free), "restricted_share_pct_rounded": pct(restricted),
        "share_table_reconciled": True,
        "document_signature_date": "2018-12-18" if signature_observed else None,
        "archive_path_date": "2018-12-28",
        "historical_first_availability_verified": False,
        "historical_otc_quote_independently_verified": False,
        "individual_entitlement_verified": False,
        "actual_fill_verified": False, "decision_authority": False,
    }


def _child(path: Path) -> None:
    result = {"started_at": datetime.now(UTC).isoformat(), "url": URL}
    try:
        obs = retrieve_pdf_bytes(URL, max_bytes=MAX_BYTES)
        result |= {"status": "OBSERVED", "body": base64.b64encode(obs.data).decode("ascii"),
                   "sha256": obs.sha256, "retrieved_at": obs.retrieved_at}
    except Exception as exc:
        result |= {"status": "BLOCK", "error": type(exc).__name__}
    result["finished_at"] = datetime.now(UTC).isoformat()
    write_worker_result(path, result, max_bytes=6 * 1024 * 1024)


def observe() -> dict:
    before = datetime.now(UTC)
    task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.public_relisting_issuer_control",
                            "--child"), timeout_seconds=30, max_bytes=6 * 1024 * 1024)
    result = {"status": "BLOCK", "worker_status": task.status, "elapsed_seconds": task.elapsed_seconds,
              "url": URL, "raw_body_retained": False, "research_only": True,
              "execution_allowed": False, "decision_authority": False}
    if task.status != "OK" or task.payload is None:
        return result
    try:
        p = task.payload
        start, end = datetime.fromisoformat(p["started_at"]), datetime.fromisoformat(p["finished_at"])
        if start.utcoffset() is None or end.utcoffset() is None or not before <= start <= end <= datetime.now(UTC):
            raise ValueError("RELIST_ISSUER_CLOCK")
        result |= {"started_at": p["started_at"], "finished_at": p["finished_at"]}
        if p["url"] != URL or p["status"] != "OBSERVED":
            return result | {"error": p.get("error", "RELIST_ISSUER_SCOPE")}
        retrieved = datetime.fromisoformat(p["retrieved_at"])
        if retrieved.utcoffset() is None or not start <= retrieved <= end:
            raise ValueError("RELIST_ISSUER_CLOCK")
        body = base64.b64decode(p["body"], validate=True)
        validate_pdf_shape(body, max_bytes=MAX_BYTES)
        if hashlib.sha256(body).hexdigest() != p["sha256"]:
            raise ValueError("RELIST_ISSUER_HASH")
        with TemporaryDirectory() as temp:
            path = Path(temp) / "notice.pdf"
            path.write_bytes(body)
            reopened = path.read_bytes()
            if reopened != body:
                raise ValueError("RELIST_ISSUER_REOPEN_HASH")
        result |= {"bytes": len(reopened), "sha256": p["sha256"], "parent_rehash": "MATCH",
                   "temporary_rehash": "MATCH", "retrieved_at": p["retrieved_at"]}
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(reopened), strict=True)
        if reader.is_encrypted or len(reader.pages) != 20:
            raise ValueError("RELIST_ISSUER_PAGE_SCOPE")
        return result | {"status": "WARN", "page_count": len(reader.pages),
                         "fields": parse_notice(tuple(reader.pages[i].extract_text() or "" for i in PAGES))}
    except Exception as exc:
        message = str(exc)
        return result | {"error": message if re.fullmatch(r"[A-Z0-9_]{3,80}", message) else type(exc).__name__}


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    result = observe() | {"executor_commit": os.environ["GITHUB_SHA"]}
    print("PUBLIC_RELISTING_ISSUER " + json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False), flush=True)
    return 0 if result["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        _child(Path(sys.argv[2]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
