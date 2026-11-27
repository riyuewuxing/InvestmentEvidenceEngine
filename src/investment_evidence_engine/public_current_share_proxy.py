"""Current case dated share count and valuation proxy; not current capital admission."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from .bounded_worker import run_json_worker, write_worker_result
from .issuer_disclosure_index import OBSERVED_ORG_ID, observe
from .official_pdf_transport import retrieve_pdf_bytes, validate_pdf_shape
from .public_symbol_change_control import compact

LIMIT = 2 * 1024 * 1024
ROOT = "https://static.cninfo.com.cn/"
# Fixed prior public receipt fields, NOT new independent source observations:
# Q3 pressure run 45820428540 job 139910950696 (2026-11-26),
# current price run 45975330448 job 140425520748 (2026-11-27).
PARENT_EQUITY = Decimal("10870742306.53")
PRICE = Decimal("3.95")
Q3_RAW_HASH = "dedeb15450b3005cb8f509cf1d3409347a76170ae5c7e9c5f21de04645ea3639"
PRICE_NORMALIZED_HASH = "2c2a393c675a6eb1aa4395d1a23dc35c117ca35f450446f18e80049988d0cd06"


def select_meeting(index: dict) -> dict:
    if index.get("status") != "OBSERVED" or index.get("query_window") != ["2026-11-06", "2026-11-09"]:
        raise ValueError("MEETING_INDEX_BLOCK")
    rows = [r for r in index["records"] if r["title"].endswith("2026年第二次临时股东会决议公告")]
    if len(rows) != 1:
        raise ValueError("MEETING_NOT_UNIQUE")
    r = rows[0]
    if r["path_day"] != "2026-11-07" or not re.fullmatch(
            r"finalpage/2026-11-07/[0-9]{1,24}\.PDF", r["attachment"]):
        raise ValueError("MEETING_PATH")
    return r


def parse_share_count(pages: tuple[str, ...]) -> int:
    if not pages or not 1 <= len(pages) <= 10:
        raise ValueError("MEETING_PAGES")
    first = compact(pages[0])
    if not all(compact(x) in first for x in ("证券代码:000035", "中国天楹股份有限公司",
                   "2026年第二次临时股东会决议公告",
                   "截至本次股东会股权登记日2026年10月30日,公司股份总数2,388,032,769股")):
        raise ValueError("MEETING_SHARE_ANCHOR")
    return 2388032769


def proxy(shares: int) -> dict:
    if type(shares) is not int or shares != 2388032769:
        raise ValueError("MEETING_SHARE_COUNT")
    capitalization = PRICE * shares
    return {"status": "DATED_DENOMINATOR_SENSITIVITY_ONLY",
            "price_cny": str(PRICE), "price_session": "2026-11-27",
            "price_source_job": 140425520748, "price_normalized_sha256": PRICE_NORMALIZED_HASH,
            "shares": shares, "share_count_as_of": "2026-10-30",
            "equity_cny": str(PARENT_EQUITY), "equity_as_of": "2026-09-30",
            "equity_source_job": 139910950696, "equity_raw_sha256": Q3_RAW_HASH,
            "assumption": "OCT30_SHARE_COUNT_UNCHANGED_TO_NOV27_NOT_VERIFIED",
            "conditional_capitalization_cny": str(capitalization),
            "conditional_pb": str((capitalization / PARENT_EQUITY).quantize(Decimal("0.0001"))),
            "current_share_count_verified": False, "current_market_cap_verified": False,
            "current_fair_value_estimated": False, "historical_pit": False,
            "decision_authority": False, "execution_allowed": False}


def child(url: str, path: Path) -> None:
    if not re.fullmatch(re.escape(ROOT) + r"finalpage/2026-11-07/[0-9]{1,24}\.PDF", url):
        raise ValueError("MEETING_ROUTE")
    obs = retrieve_pdf_bytes(url, max_bytes=LIMIT)
    write_worker_result(path, {"url": url, "body": base64.b64encode(obs.data).decode("ascii"),
                               "sha256": obs.sha256, "retrieved_at": obs.retrieved_at},
                        max_bytes=3 * LIMIT)


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    index, _ = observe("meeting", OBSERVED_ORG_ID)
    out = {"status": "BLOCK", "index": index, "executor_commit": os.environ["GITHUB_SHA"],
           "decision_authority": False, "execution_allowed": False, "raw_body_retained": False}
    try:
        row = select_meeting(index)
        url = ROOT + row["attachment"]
        a = datetime.now(UTC)
        worker = run_json_worker((sys.executable, "-m", "investment_evidence_engine.public_current_share_proxy",
                                  "--child", url), timeout_seconds=30, max_bytes=3 * LIMIT)
        out |= {"url": url, "worker_status": worker.status, "elapsed_seconds": worker.elapsed_seconds}
        if worker.status != "OK" or worker.payload is None:
            raise ValueError("MEETING_WORKER_BLOCK")
        p = worker.payload
        retrieved = datetime.fromisoformat(p["retrieved_at"])
        raw = base64.b64decode(p["body"], validate=True)
        validate_pdf_shape(raw, max_bytes=LIMIT)
        if p["url"] != url or not a <= retrieved <= datetime.now(UTC) or hashlib.sha256(raw).hexdigest() != p["sha256"]:
            raise ValueError("MEETING_RECEIPT")
        out |= {"bytes": len(raw), "sha256": p["sha256"], "parent_rehash": "MATCH", "retrieved_at": p["retrieved_at"]}
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 10:
            raise ValueError("MEETING_PAGES")
        pages = tuple(page.extract_text() or "" for page in reader.pages)
        out |= {"page_count": len(pages), "page1_sha256": hashlib.sha256(compact(pages[0]).encode()).hexdigest()}
        out |= {"status": "WARN", "proxy": proxy(parse_share_count(pages))}
    except Exception as e:
        msg = str(e)
        out |= {"error": msg if re.fullmatch(r"[A-Z0-9_]{3,80}", msg) else type(e).__name__}
    print("PUBLIC_CURRENT_SHARE_PROXY " + json.dumps(out | {"observed_cutoff": datetime.now(UTC).isoformat()},
              ensure_ascii=False, sort_keys=True, allow_nan=False), flush=True)
    return 0 if out["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        child(sys.argv[2], Path(sys.argv[3]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
