"""Observe fixed tax policy HTML and compute a new sensitivity from a prior derived receipt."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from .bounded_worker import run_json_worker, write_worker_result
from .dividend_tax_sensitivity import RULE_URLS, uniform_tax_tiers
from .issuer_disclosure_index import NoRedirect
from .snapshot_integrity import strict_json_loads
from .sse_lifecycle_control import VisibleHTML, normalized

REPO = "riyuewuxing/InvestmentEvidenceEngine"
MAX_BYTES = 1024*1024
SOURCES = dict(zip(("rule_2015", "official_explanation"), RULE_URLS, strict=True))
RECEIPT = Path("fixtures/corporate_actions/observed_000035_momentum_entitlement.json")
RUN, JOB = 45860749145, 140050813661
PRIOR_EXECUTOR = "b18eca6f4d4249bb51d44b9a38aecaa998246e99"
SIGNAL_SHA = "4cfa27ad4f03e5877d5a06e14e90a814240bb41c532ec5631a7c4d33c593e4e3"


def parse_policy(key: str, body: bytes) -> dict:
    p = VisibleHTML()
    p.feed(body.decode("utf-8-sig", errors="strict"))
    p.close()
    text = normalized(" ".join(p.parts))
    if key == "rule_2015":
        markers = ("财税〔2015〕101号", "持股期限超过1年的", "暂免征收个人所得税",
                   "持股期限在1个月以内(含1个月)的", "全额计入应纳税所得额",
                   "持股期限在1个月以上至1年(含1年)的", "暂减按50%计入应纳税所得额",
                   "统一适用20%的税率", "暂不扣缴个人所得税", "待个人转让股票时",
                   "2015年9月8日起施行")
        fields = {"effective_from": "2015-09-08", "ordinary_individual_rates_pct": [20, 10, 0],
                  "transfer_time_collection_for_holding_le_one_year": True}
    elif key == "official_explanation":
        markers = ("股息红利差别化个人所得税政策调整有关问题答记者问",
                   "实际税负仍为20%和10%", "持股超过1年的", "暂免征收个人所得税",
                   "转让交割该股票之日前一日", "先进先出法", "按自然年(月)计算")
        fields = {"natural_calendar_year_month": True, "fifo": True,
                  "holding_end_is_day_before_transfer_settlement": True}
    else:
        raise ValueError("DIVIDEND_TAX_POLICY_KEY")
    if not all(normalized(marker) in text for marker in markers):
        raise ValueError("DIVIDEND_TAX_POLICY_FIELDS")
    return fields | {"historical_availability_verified": False, "current_applicability_to_account_verified": False}


def child(key: str, path: Path) -> None:
    url = SOURCES[key]
    start = datetime.now(UTC)
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"})
        with build_opener(NoRedirect()).open(req, timeout=12) as response:
            if (response.status != 200 or response.geturl() != url
                    or response.headers.get("Content-Range") is not None
                    or response.headers.get("Content-Encoding", "identity").lower() not in ("", "identity")):
                raise ValueError("DIVIDEND_TAX_HTTP_SCOPE")
            body = response.read(MAX_BYTES+1)
            length = response.headers.get("Content-Length")
            if not 0 < len(body) <= MAX_BYTES or (length is not None and int(length) != len(body)):
                raise ValueError("DIVIDEND_TAX_BODY_LIMIT")
        result = {"key": key, "url": url, "started_at": start.isoformat(),
                  "observed_at": datetime.now(UTC).isoformat(),
                  "sha256": hashlib.sha256(body).hexdigest(),
                  "body": base64.b64encode(body).decode("ascii")}
    except (OSError, ValueError) as exc:
        result = {"key": key, "error": type(exc).__name__,
                  "http_status": exc.code if isinstance(exc, HTTPError) else None}
    write_worker_result(path, result)


def observe(key: str) -> dict:
    url = SOURCES[key]
    out = {"key": key, "url": url, "status": "BLOCK", "raw_body_retained": False}
    worker = run_json_worker((sys.executable, "-m", "investment_evidence_engine.dividend_tax_control",
                              "--child", key), timeout_seconds=25, max_bytes=2*MAX_BYTES)
    out |= {"worker_status": worker.status, "elapsed_seconds": worker.elapsed_seconds}
    if worker.status != "OK" or worker.payload is None:
        return out
    try:
        p = worker.payload
        if p["key"] != key:
            raise ValueError("DIVIDEND_TAX_RECEIPT_KEY")
        if "error" in p:
            return out | {"error": p["error"], "http_status": p.get("http_status")}
        a, b = datetime.fromisoformat(p["started_at"]), datetime.fromisoformat(p["observed_at"])
        body = base64.b64decode(p["body"], validate=True)
        digest = hashlib.sha256(body).hexdigest()
        if (p["url"] != url or a.utcoffset() is None or b.utcoffset() is None
                or not a <= b <= datetime.now(UTC) or digest != p["sha256"]
                or not 0 < len(body) <= MAX_BYTES):
            raise ValueError("DIVIDEND_TAX_RECEIPT_SCOPE")
        out |= {"bytes": len(body), "sha256": digest, "parent_rehash": "MATCH",
                "observed_at": b.isoformat()}
        return out | {"status": "OBSERVED", "fields": parse_policy(key, body)}
    except (ValueError, TypeError, KeyError) as exc:
        return out | {"error": str(exc) if str(exc).startswith("DIVIDEND_TAX_") else type(exc).__name__}


def calculate_from_receipt(value: dict) -> list[dict]:
    prior = value["receipt"]
    if (value.get("run_id") != RUN or value.get("job_id") != JOB
            or value.get("derived_receipt_not_original_market") is not True
            or prior.get("executor_commit") != PRIOR_EXECUTOR or prior.get("status") != "WARN"
            or prior.get("observed_signal_rows_sha256") != SIGNAL_SHA
            or prior.get("prior_exact_price_baseline_recomputed") != "MATCH"
            or prior.get("pit_safe") is not False):
        raise ValueError("DIVIDEND_TAX_PRIOR_RECEIPT_SCOPE")
    calculation = prior["calculation"]
    if calculation.get("status") != "CONDITIONAL_SEGREGATED_GROSS_ENTITLEMENT_SENSITIVITY":
        raise ValueError("DIVIDEND_TAX_PRIOR_CALCULATION_SCOPE")
    result = []
    segments = calculation["segments"]
    if [s["segment"] for s in segments] != ["train_reference", "validation_reference", "test_reference"]:
        raise ValueError("DIVIDEND_TAX_PRIOR_SEGMENTS")
    for segment in segments:
        if [c["one_way_bps"] for c in segment["stress"]] != [10, 20, 30]:
            raise ValueError("DIVIDEND_TAX_PRIOR_STRESS")
        for case in segment["stress"]:
            for strategy in ("signal_rule", "constant_invested", "flat_cash_assumed_zero_interest"):
                r = case[strategy]
                base = r["price_only"]["net_price_change_pct"]
                gross = r["gross_entitlement_increment_pp"]
                event_sum = 100*math.fsum(e["gross_entitlement_per_initial_cny"] for e in r["events"])
                if (not math.isclose(event_sum, gross, abs_tol=1e-10, rel_tol=1e-12)
                        or not math.isclose(base+gross, r["price_plus_nominal_gross_entitlement_change_pct"],
                                            abs_tol=1e-10, rel_tol=1e-12)):
                    raise ValueError("DIVIDEND_TAX_PRIOR_ARITHMETIC")
                result.append({"segment": segment["segment"], "one_way_bps": case["one_way_bps"],
                               "strategy": strategy, **uniform_tax_tiers(base, gross)})
    return result


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    raw = RECEIPT.read_bytes()
    report = {"executor_commit": os.environ["GITHUB_SHA"], "status": "BLOCK",
              "prior_run_id": RUN, "prior_job_id": JOB, "derived_input_sha256": hashlib.sha256(raw).hexdigest(),
              "policy_observations": [observe(k) for k in SOURCES],
              "new_market_fetch": False, "actual_account_tax_verified": False,
              "decision_authority": False, "execution_allowed": False, "pit_safe": False}
    try:
        report["tax_sensitivity"] = calculate_from_receipt(strict_json_loads(raw))
        if all(r["status"] == "OBSERVED" for r in report["policy_observations"]):
            report["status"] = "WARN"
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        report["blocker"] = str(exc) if str(exc).startswith("DIVIDEND_TAX_") else type(exc).__name__
    print("PUBLIC_DIVIDEND_TAX " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child" and sys.argv[2] in SOURCES:
        child(sys.argv[2], Path(sys.argv[3]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
