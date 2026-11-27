"""Actual offline PDF locator validation on a lawfully retained public original."""
from __future__ import annotations

import json
import os
from importlib.metadata import version
from pathlib import Path

from investment_evidence_engine.pdf_page_guard import observe_pdf_page_count, validate_page_span

DIGEST = "d91f1329ce9e7a13c875cdaf56ebafd1cda360a13162800833c46888fa3d0516"


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    raw = (Path("public-evidence/sha256") / (DIGEST + ".pdf")).read_bytes()
    count = observe_pdf_page_count(raw, expected_sha256=DIGEST)
    validate_page_span(actual_count=count, declared_count=40, page=40)
    rejected = {}
    for name, claimed, page in (("missing_declared_count", None, 41), ("inflated_declared_count", 41, 41)):
        try:
            validate_page_span(actual_count=count, declared_count=claimed, page=page)
        except ValueError as exc:
            rejected[name] = str(exc)
    good = count == 40 and rejected == {"missing_declared_count": "PDF_PAGE_LOCATOR_OUT_OF_RANGE",
                                       "inflated_declared_count": "PDF_PAGE_DECLARED_COUNT_MISMATCH"}
    report = {"status": "WARN" if good else "BLOCK", "executor_commit": os.environ["GITHUB_SHA"],
              "source_sha256": DIGEST, "observed_bytes": len(raw), "parser_version": version("pypdf"),
              "actual_page_count": count, "page_40_scope_verified": True,
              "bad_locators_rejected": rejected, "source_semantics_verified": False,
              "historical_first_availability_verified": False, "private_review_executed": False,
              "formal_claim_admitted": False, "research_only": True, "decision_authority": False,
              "execution_allowed": False}
    print("PUBLIC_RETAINED_PDF_LOCATOR " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if good else 2


if __name__ == "__main__":
    raise SystemExit(main())
