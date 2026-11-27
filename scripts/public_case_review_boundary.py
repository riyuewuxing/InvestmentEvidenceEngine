"""Offline replay of the actual retained public receipt metadata. No new fetch."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from investment_evidence_engine.review_boundary import original_support_blocker, stock_review_scope
from investment_evidence_engine.snapshot_integrity import strict_json_loads

PATH = Path("fixtures/current_case/observed_000035_20261127.json")


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    raw = PATH.read_bytes()
    archive_sha = hashlib.sha256(raw).hexdigest()
    data = strict_json_loads(raw)
    if not isinstance(data, dict) or data.get("scope") != "PUBLIC_CASE_OBSERVED_LOG_METADATA_ONLY":
        raise ValueError("REVIEW_ARCHIVE_SCOPE")
    if len(data["receipts"]) != 8:
        raise ValueError("REVIEW_ARCHIVE_COUNT")
    receipt_rejections = {}
    for key, receipt in data["receipts"].items():
        body = receipt["line"].split(" " + receipt["marker"] + " ", 1)[1].encode()
        digest = hashlib.sha256(body).hexdigest()
        receipt_rejections[key] = {"sha256": digest, "reason": original_support_blocker(
            body, source_class="RELABELLED_ORIGINAL", expected_sha256=digest)}
    reason = original_support_blocker(raw, source_class="RELABELLED_ORIGINAL", expected_sha256=archive_sha)
    price = next(v for k, v in data["receipts"].items() if k == "price")
    rows = strict_json_loads(price["line"].split(" " + price["marker"] + " ", 1)[1].encode())["terminal_observations"]
    symbols = sorted({row["symbol"] for row in rows})
    routes = {symbol: stock_review_scope(symbol) for symbol in symbols}
    passed = (reason == "SUPPORT_METADATA_ONLY"
              and all(x["reason"] == "SUPPORT_METADATA_ONLY" for x in receipt_rejections.values())
              and routes == {"000035": "sz000035", "510300": None})
    report = {"status": "WARN" if passed else "BLOCK", "executor_commit": os.environ["GITHUB_SHA"],
              "archive_sha256": archive_sha, "archive_relabelled_as_original_reason": reason,
              "actual_receipts_rejected_as_original_support": receipt_rejections,
              "stock_route_syntax_only": routes, "stock_route_is_verified_listing": False,
              "private_review_executed": False, "formal_claim_admitted": False,
              "formal_historical_profile_admitted": False, "research_only": True,
              "decision_authority": False, "execution_allowed": False}
    print("PUBLIC_CASE_REVIEW_BOUNDARY " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
