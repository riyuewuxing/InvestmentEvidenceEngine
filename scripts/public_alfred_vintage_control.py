"""One public-only ALFRED vintage experiment with actual retained BLS originals."""
import json
import os

from replay_bls_archive import retained_revisions

from investment_evidence_engine.alfred_vintage_control import VINTAGES, compare_vintages, observe

if __name__ == "__main__":
    if os.environ["GITHUB_REPOSITORY"] != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    # Reuse existing original bytes and parser; no BLS network requests.
    originals = retained_revisions()
    receipts = [observe(vintage) for vintage in VINTAGES]
    comparison = compare_vintages(receipts, tuple(int(row.value) for row in originals))
    report = comparison | {
        "executor_commit": os.environ["GITHUB_SHA"],
        "source_attribution": "U.S. Bureau of Labor Statistics via ALFRED, Federal Reserve Bank of St. Louis",
        "vintage_semantics": "https://alfred.stlouisfed.org/help/downloaddata",
        "original_source_sha256": [row.raw_sha256 for row in originals],
        "receipts": receipts, "raw_vendor_body_retained": False,
        "pit_safe": False, "decision_authority": False, "execution_allowed": False,
        "research_only": True,
    }
    print("ALFRED_VINTAGE_CONTROL " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    raise SystemExit(0 if report["status"] == "WARN" else 2)
