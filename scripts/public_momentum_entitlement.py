"""New calculation on an exact re-observed signal projection, not a repeat price test.

Both event receipts originate from prior public runner logs. A fresh Tencent
body is necessary because original historical rows were not retained. Its
consumed projection and unchanged baseline must match the prior actual receipt.
No full input version, private decision, or historical availability claim.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from public_selected_action_reconciliation import terms_from_receipt

from investment_evidence_engine.historical_capture import PublicSecurity
from investment_evidence_engine.holding_risk import CashDistribution, CashDistributionInputs
from investment_evidence_engine.market_calendar import scheduled_days
from investment_evidence_engine.momentum_entitlement import momentum_entitlement_profile
from investment_evidence_engine.research_profile_evidence import canonical_sha256
from investment_evidence_engine.retrospective_control import acquire_tencent
from investment_evidence_engine.snapshot_integrity import strict_json_loads

REPO = "riyuewuxing/InvestmentEvidenceEngine"
SUBJECT = PublicSecurity(symbol="000035", asset_type="STOCK")
FIRST, LAST = date(2025, 1, 2), date(2026, 11, 25)
ROOT = Path(__file__).resolve().parents[1]
PRIOR_SIGNAL_SHA = "4cfa27ad4f03e5877d5a06e14e90a814240bb41c532ec5631a7c4d33c593e4e3"
PRIOR_BASE = ROOT/"fixtures/research_profile/observed_20261126_000035_diagnostic.json"
DERIVED_RECEIPT_SHA = {2025: "fdf46e5df5f44cfe4b243038e74cb7d4ccd7e25a46c33f32d05f3773ac8ac2ec",
                       2026: "2a5e6cc7c5dceb25ca568b33b62c3476d36946ee3fc37e6fc95b84f40dae40d2"}
PRIOR_BASELINE_SHA = "b6424c54dc79fa3575f74c8657a3a8a9decf8c7ae2aa9ed81dd1e15dd27170ae"
EVENTS = (
    (2025, 45856529066, 140036250613, "18ad09cf3d97f04fdff90b2ee0bee63380a021862098caefbbd9455cc97b15e8"),
    (2026, 45856977986, 140037820223, "206b923f9f1e0d12b6e5b20d77dc3b39eb57058da141b5358c2dd49952d540af"),
)


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    report = {"status": "BLOCK", "executor_commit": os.environ["GITHUB_SHA"],
              "subject": SUBJECT.symbol, "first": FIRST.isoformat(), "last": LAST.isoformat(),
              "decision_authority": False, "execution_allowed": False, "pit_safe": False,
              "prior_full_market_version_match_claimed": False, "raw_provider_bytes_retained": False}
    try:
        terms = []
        receipts = []
        for year, run, job, sha in EVENTS:
            raw = (ROOT/f"fixtures/corporate_actions/observed_000035_{year}_cash_receipt.json").read_bytes()
            if hashlib.sha256(raw).hexdigest() != DERIVED_RECEIPT_SHA[year]:
                raise ValueError("ENTITLEMENT_DERIVED_RECEIPT_VERSION_MISMATCH")
            prior = strict_json_loads(raw)
            if (prior["run_id"], prior["job_id"], prior["receipt"]["source_sha256"]) != (run, job, sha):
                raise ValueError("ENTITLEMENT_PRIOR_EVENT_RECEIPT_SCOPE")
            if prior["derived_receipt_not_original_pdf"] is not True:
                raise ValueError("ENTITLEMENT_PRIOR_EVENT_RECEIPT_TYPE")
            terms.append(terms_from_receipt(prior["receipt"]))
            receipts.append({"year": year, "run": run, "job": job, "source_sha256": sha,
                             "derived_receipt_sha256": hashlib.sha256(raw).hexdigest()})
        report["prior_event_receipts"] = receipts
        inputs = CashDistributionInputs(events=tuple(CashDistribution(
            subject_id=t.symbol, disclosed_date=t.disclosed_date, ex_date=t.ex_date,
            gross_cash_per_unit_cny=float(t.gross_per_share), source_locator=t.source_locator) for t in terms))
        frame, info = acquire_tencent(SUBJECT.symbol, FIRST, LAST)
        report["tencent"] = info
        if frame is None:
            raise ValueError("ENTITLEMENT_MARKET_SOURCE_BLOCK")
        dates = tuple(frame["date"].dt.date)
        if dates != tuple(r.day for r in scheduled_days(FIRST, LAST) if r.is_trading_day):
            raise ValueError("ENTITLEMENT_MARKET_CALENDAR")
        opens, closes = frame["open"].tolist(), frame["close"].tolist()
        projection = [[d.isoformat(), float(o), float(c)] for d, o, c in zip(dates, opens, closes, strict=True)]
        signal_digest = canonical_sha256(projection)
        report |= {"prior_signal_rows_sha256": PRIOR_SIGNAL_SHA, "observed_signal_rows_sha256": signal_digest}
        if signal_digest != PRIOR_SIGNAL_SHA:
            raise ValueError("ENTITLEMENT_PRIOR_SIGNAL_PROJECTION_MISMATCH")
        # Re-open the exact consumed projection; no reuse of an unverified
        # prior market version or assumed data array.
        with TemporaryDirectory() as temp:
            path = Path(temp)/"projection.json"
            body = json.dumps(projection, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"), allow_nan=False).encode()
            path.write_bytes(body)
            readback = path.read_bytes()
            if readback != body or hashlib.sha256(readback).hexdigest() != signal_digest:
                raise ValueError("ENTITLEMENT_PROJECTION_REHASH")
            rows = strict_json_loads(readback)
            result = momentum_entitlement_profile(tuple(date.fromisoformat(r[0]) for r in rows),
                [r[2] for r in rows], [r[1] for r in rows], subject=SUBJECT,
                events=inputs, reference_terms=tuple(terms))
        prior_baseline = strict_json_loads(PRIOR_BASE.read_bytes())
        if (canonical_sha256(prior_baseline) != PRIOR_BASELINE_SHA
                or canonical_sha256(prior_baseline) != canonical_sha256(result["price_only_baseline"])):
            raise ValueError("ENTITLEMENT_PRIOR_PRICE_BASELINE_MISMATCH")
        report |= {"status": "WARN", "prior_signal_projection_match": True,
                   "temporary_projection_rehash": "MATCH",
                   "prior_exact_price_baseline_recomputed": "MATCH",
                   "prior_baseline_sha256": canonical_sha256(prior_baseline),
                   "calculation": result}
    except (ValueError, TypeError, KeyError, OSError, ArithmeticError, RuntimeError) as exc:
        report["blocker"] = str(exc) if str(exc).startswith("ENTITLEMENT_") else type(exc).__name__
    print("PUBLIC_MOMENTUM_ENTITLEMENT " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
