"""One bounded, licensed original-byte retention control, not a production worker."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from datetime import UTC, datetime

from investment_evidence_engine.bounded_worker import run_json_worker
from investment_evidence_engine.twse_revenue_control import URLS, parse_exchange

EXPECTED_SHA256 = "0e6a2cbfb78befd2c77415e57aadfdf7acc1038a48e9d815bedb113730b622f2"
EXPECTED_SIZE = 207911
SOURCE = "https://data.gov.tw/dataset/18420"
LICENSE = "https://data.gov.tw/license"


def verify_snapshot(raw: bytes, observed: datetime) -> dict:
    if len(raw) != EXPECTED_SIZE or hashlib.sha256(raw).hexdigest() != EXPECTED_SHA256:
        raise ValueError("TWSE_ARCHIVE_EXACT_VERSION_MISMATCH")
    fields = parse_exchange(raw, observed)
    if (fields["source_rows_observed"] != 1091 or fields["snapshot_date"] != "2026-11-17"
            or fields["amounts"] != [586890319, 511857399, 367473051, 4485617293, 3130436902]):
        raise ValueError("TWSE_ARCHIVE_SCOPE_MISMATCH")
    return fields


def main() -> int:
    if os.environ["GITHUB_REPOSITORY"] != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    out = {"status": "BLOCK", "executor_commit": os.environ["GITHUB_SHA"],
           "source": SOURCE, "license": LICENSE, "source_url": URLS["exchange"],
           "source_attribution": "金融監督管理委員會證券期貨局／臺灣證券交易所，2026，上市公司每月營業收入彙總表",
           "expected_sha256": EXPECTED_SHA256, "pit_safe": False,
           "historical_capture_verified": False, "decision_authority": False,
           "execution_allowed": False}
    task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.twse_revenue_control",
                            "--child", "exchange"), timeout_seconds=30, max_bytes=512 * 1024)
    out |= {"worker_status": task.status, "elapsed_seconds": task.elapsed_seconds}
    if task.status == "OK" and task.payload is not None:
        try:
            p = task.payload
            if "error" in p:
                out |= {"error": p["error"], "http_status": p.get("http_status")}
            else:
                a, b = datetime.fromisoformat(p["started_at"]), datetime.fromisoformat(p["retrieved_at"])
                raw = base64.b64decode(p["body"], validate=True)
                digest = hashlib.sha256(raw).hexdigest()
                if (p["kind"] != "exchange" or p["url"] != URLS["exchange"]
                        or a.utcoffset() is None or b.utcoffset() is None
                        or not a <= b <= datetime.now(UTC) or digest != p["sha256"]):
                    raise ValueError("TWSE_ARCHIVE_RECEIPT_MISMATCH")
                out |= {"retrieved_at": b.isoformat(), "sha256": digest, "bytes": len(raw),
                        "parent_rehash": "MATCH"}
                out["fields"] = verify_snapshot(raw, b)
                out["status"] = "EXACT_PRIOR_DIGEST_MATCH"
                print("TWSE_ARCHIVE_RECEIPT " + json.dumps(out, sort_keys=True, ensure_ascii=False), flush=True)
                encoded = base64.b64encode(raw).decode("ascii")
                for i in range(0, len(encoded), 4096):
                    print(f"TWSE_ARCHIVE_BYTES {i//4096:04d} {encoded[i:i+4096]}", flush=True)
                print("TWSE_ARCHIVE_END " + str(len(encoded)), flush=True)
                return 0
        except (KeyError, ValueError, TypeError) as exc:
            out["error"] = str(exc) if str(exc).startswith("TWSE_") else type(exc).__name__
    print("TWSE_ARCHIVE_RECEIPT " + json.dumps(out, sort_keys=True, ensure_ascii=False), flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
