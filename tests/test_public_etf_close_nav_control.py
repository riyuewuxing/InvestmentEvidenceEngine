"""Regression over retained, derived public report cells (not live I/O)."""
import json

import pytest

from investment_evidence_engine.etf_report_diagnostics import closing_premium, compare_reports
from investment_evidence_engine.public_etf_close_nav_control import RECEIPT, verify_report_fields


def test_pinned_observed_report_fields_reconcile():
    raw = RECEIPT.read_bytes()
    docs = verify_report_fields(raw)["documents"]
    comparison = compare_reports(*(d["fields"] for d in docs))
    assert comparison["paired_reported_horizons"]["3M"]["left_minus_right_nav_return_pp"] == "-0.07"
    assert comparison["paired_reported_horizons"]["1Y"]["left_minus_right_nav_return_pp"] == "0.26"
    assert comparison["left"]["net_creation_units"] == "1017900000"
    assert comparison["right"]["net_creation_units"] == "-6000000.00"
    # Fixed historical source observations from run 45958611216.
    for d, price, ratio in zip(docs, ("4.621", "1.192"), ("0.006493", "0.016781"), strict=True):
        result = closing_premium(d["fields"], symbol=d["symbol"], session="2026-09-30", raw_close=price)
        assert result["close_over_reported_nav_minus_one_pct"] == ratio
        assert not result["decision_authority"]


def test_modified_retained_report_fields_rejected():
    data = json.loads(RECEIPT.read_bytes())
    data["documents"][0]["fields"]["end_nav_cny"] = "4.6208"
    with pytest.raises(ValueError, match="ETF_REPORT_RECEIPT_HASH"):
        verify_report_fields(json.dumps(data).encode())
