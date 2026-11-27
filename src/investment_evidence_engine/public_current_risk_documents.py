"""Fixed current issuer risk notices, not an exhaustive corporate action or debt ledger."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from .bounded_worker import run_json_worker, write_worker_result
from .official_pdf_transport import retrieve_pdf_bytes, validate_pdf_shape
from .public_symbol_change_control import compact

REPO = "riyuewuxing/InvestmentEvidenceEngine"
MAX_BYTES = 2 * 1024 * 1024
DOCS = {
    "pledge": ("2026-11-19/1225677917.PDF", "000035"),
    "guarantee": ("2026-11-20/1225679474.PDF", "000035"),
    "release": ("2026-11-25/1225685289.PDF", "000035"),
}


def url_for(key: str) -> str:
    return "https://static.cninfo.com.cn/finalpage/" + DOCS[key][0]


def present(text: str, *variants: str) -> bool:
    return any(compact(v) in text for v in variants)


def parse_notice(key: str, pages: tuple[str, ...]) -> dict:
    if key not in DOCS or not 1 <= len(pages) <= 5 or any(not isinstance(p, str) for p in pages):
        raise ValueError("RISK_PAGE_SCOPE")
    first = compact(pages[0])
    full = compact(" ".join(pages))
    checks = {
        "identity": present(first, "证券代码:000035", "证券代码000035") and present(first, "中国天楹股份有限公司"),
    }
    if key == "pledge":
        checks |= {
            "title": present(first, "关于公司实际控制人进行股票质押式回购交易的公告"),
            "increment": present(full, "3,810万股", "3810万股", "3,810.00", "3810.00", "38,100,000"),
            "before": present(full, "37,322.8065", "37322.8065", "373,228,065"),
            "after": present(full, "41,132.8065", "41132.8065", "411,328,065"),
            "group_holding": present(full, "61,215.2769", "61215.2769", "612,152,769"),
            "group_ratio": present(full, "67.19%"),
            "issuer_ratio": present(full, "17.22%"),
        }
        fields = {"kind": "CONTROLLER_GROUP_PLEDGE", "new_pledged_shares": 38100000,
                  "before_group_pledged_shares": 373228065, "after_group_pledged_shares": 411328065,
                  "group_holdings_shares": 612152769, "reported_group_pct": "67.19",
                  "reported_issuer_pct": "17.22"}
    elif key == "release":
        checks |= {
            "title": present(first, "关于控股股东部分股份解除质押的公告"),
            "released": present(full, "3,225.8065", "3225.8065", "32,258,065"),
            "after": present(full, "37,907", "37907", "379,070,000"),
            "group_holding": present(full, "61,215.2769", "61215.2769", "612,152,769"),
            "group_ratio": present(full, "61.92%"),
            "issuer_ratio": present(full, "15.87%"),
        }
        fields = {"kind": "CONTROLLER_GROUP_RELEASE", "released_shares": 32258065,
                  "after_group_pledged_shares": 379070000, "group_holdings_shares": 612152769,
                  "reported_group_pct": "61.92", "reported_issuer_pct": "15.87"}
    else:
        checks |= {
            "title": present(first, "关于为子公司提供担保的公告"),
            "subsidiary": present(full, "宁夏天楹"),
            "principal": present(full, "5,000万元", "5000万元", "5,000.00万元", "5,000.00"),
            "aggregate": present(full, "148.42亿元", "148.42"),
            "ratio": present(full, "133.86%"),
            "ownership": present(full, "95%"),
            "joint": present(full, "连带责任"),
        }
        fields = {"kind": "SUBSIDIARY_GUARANTEE", "reported_principal_cny": 50000000,
                  "reported_aggregate_guarantees_cny": 14842000000,
                  "reported_aggregate_to_audited_net_assets_pct": "133.86",
                  "reported_ownership_pct": "95", "joint_liability_reported": True}
    # Do not output a value if any anchor for that notice fails.
    return {"anchor_checks": checks, "fields": fields if all(checks.values()) else None}


def summarize(notices: list[dict]) -> dict:
    verified = {r["key"]: r["fields"] for r in notices
                if r["status"] == "OBSERVED" and r.get("fields") is not None}
    pledge, release = verified.get("pledge"), verified.get("release")
    bridge = None
    if pledge and release:
        bridge = (pledge["before_group_pledged_shares"] + pledge["new_pledged_shares"]
                  == pledge["after_group_pledged_shares"]
                  and pledge["after_group_pledged_shares"] - release["released_shares"]
                  == release["after_group_pledged_shares"]
                  and pledge["group_holdings_shares"] == release["group_holdings_shares"])
    return {"status": "WARN" if len(verified) == 3 and bridge is True else "BLOCK",
            "notices": notices, "pledge_snapshot_arithmetic_match": bridge,
            "complete_intervening_events_verified": False, "controller_debt_is_issuer_debt": False,
            "actual_margin_threshold_verified": False, "guarantees_additive_to_consolidated_debt": False,
            "guarantee_actual_payment_verified": False, "historical_first_availability_verified": False,
            "durable_original_bytes_verified": False, "decision_authority": False,
            "execution_allowed": False, "research_only": True}


def _child(key: str, path: Path) -> None:
    started = datetime.now(UTC)
    payload = {"key": key, "url": url_for(key), "started_at": started.isoformat()}
    try:
        obs = retrieve_pdf_bytes(url_for(key), max_bytes=MAX_BYTES)
        payload |= {"status": "OBSERVED", "body": base64.b64encode(obs.data).decode("ascii"),
                    "sha256": obs.sha256, "retrieved_at": obs.retrieved_at}
    except Exception as exc:
        payload |= {"status": "BLOCK", "error": type(exc).__name__}
    payload["finished_at"] = datetime.now(UTC).isoformat()
    write_worker_result(path, payload, max_bytes=3 * MAX_BYTES)


def observe(key: str) -> dict:
    before = datetime.now(UTC)
    worker = run_json_worker((sys.executable, "-m", "investment_evidence_engine.public_current_risk_documents",
                              "--child", key), timeout_seconds=30, max_bytes=3 * MAX_BYTES)
    out = {"key": key, "url": url_for(key), "status": "BLOCK",
           "worker_status": worker.status, "elapsed_seconds": worker.elapsed_seconds,
           "raw_body_retained": False}
    if worker.status != "OK" or worker.payload is None:
        return out
    try:
        p = worker.payload
        if (p["key"], p["url"]) != (key, url_for(key)):
            raise ValueError("CURRENT_RISK_RECEIPT_SCOPE")
        a, b = (datetime.fromisoformat(p[k]) for k in ("started_at", "finished_at"))
        if a.utcoffset() is None or b.utcoffset() is None or not before <= a <= b <= datetime.now(UTC):
            raise ValueError("CURRENT_RISK_RECEIPT_CLOCK")
        out |= {"started_at": p["started_at"], "finished_at": p["finished_at"]}
        if p["status"] != "OBSERVED":
            return out | {"error": p.get("error", "CHILD_BLOCK")}
        captured = datetime.fromisoformat(p["retrieved_at"])
        if captured.utcoffset() is None or not a <= captured <= b:
            raise ValueError("CURRENT_RISK_RECEIPT_CLOCK")
        raw = base64.b64decode(p["body"], validate=True)
        validate_pdf_shape(raw, max_bytes=MAX_BYTES)
        if hashlib.sha256(raw).hexdigest() != p["sha256"]:
            raise ValueError("CURRENT_RISK_BODY_HASH")
        out |= {"bytes": len(raw), "sha256": p["sha256"], "parent_rehash": "MATCH",
                "retrieved_at": p["retrieved_at"]}
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 5:
            raise ValueError("CURRENT_RISK_PAGE_SCOPE")
        pages = tuple(page.extract_text() or "" for page in reader.pages)
        parsed = parse_notice(key, pages)
        return out | {"status": "OBSERVED" if parsed["fields"] is not None else "BLOCK",
                      "page_count": len(pages), "page_sha256": [hashlib.sha256(compact(s).encode()).hexdigest() for s in pages],
                      **parsed}
    except Exception as exc:
        msg = str(exc)
        return out | {"error": msg if re.fullmatch(r"[A-Z0-9_]{3,80}", msg) else type(exc).__name__}


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    with ThreadPoolExecutor(max_workers=2) as pool:
        notices = list(pool.map(observe, DOCS))
    result = summarize(notices) | {"executor_commit": os.environ["GITHUB_SHA"],
                                  "observed_cutoff": datetime.now(UTC).isoformat()}
    print("PUBLIC_CURRENT_RISK_DOCUMENTS " + json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False), flush=True)
    return 0 if result["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child" and sys.argv[2] in DOCS:
        _child(sys.argv[2], Path(sys.argv[3]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
