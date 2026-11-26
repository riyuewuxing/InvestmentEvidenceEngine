import json
from datetime import UTC, datetime

import pytest

from investment_evidence_engine.sec_filing_control import CIK, FILING, PERIOD, TAG, extract_concept, extract_filings

NOW = datetime(2026, 11, 26, tzinfo=UTC)


def submissions():
    data = {
        "accessionNumber": list(FILING), "form": ["10-K", "10-K"],
        "filingDate": [f[0] for f in FILING.values()], "reportDate": [f[1] for f in FILING.values()],
        "acceptanceDateTime": ["2025-10-31T10:01:26Z", "2026-11-03T13:05:15Z"],
        "primaryDocument": [f[3] for f in FILING.values()],
    }
    return {"cik": CIK, "name": "Apple Inc.", "filings": {"recent": data}}


def concept():
    return {"cik": 320193, "entityName": "Apple Inc.", "taxonomy": "us-gaap", "tag": TAG,
            "units": {"USD": [
                {"start": PERIOD[0], "end": PERIOD[1], "accn": a,
                 "filed": f[0], "form": "10-K", "val": 416161000000}
                for a, f in FILING.items()]}}


def test_acceptance_clock_not_publication():
    filings = extract_filings(json.dumps(submissions()).encode(), NOW)
    assert filings["0000320193-25-000079"]["accepted_at_new_york"] == "2025-10-31T06:01:26-04:00"
    assert filings["0000320193-26-000026"]["acceptance_not_publication_or_capture"]


def test_reject_naive_or_wrong_acceptance():
    doc = submissions()
    doc["filings"]["recent"]["acceptanceDateTime"][0] = "2025-10-31T06:01:26"
    with pytest.raises(ValueError, match="SEC_ACCEPTANCE_CLOCK_CONFLICT"):
        extract_filings(json.dumps(doc).encode(), NOW)


def test_exact_period_and_accession_are_not_latest_value():
    report = extract_concept(json.dumps(concept()).encode())
    assert report["comparison_equal"]
    assert report["values_by_accession"]["0000320193-25-000079"] == 416161000000


def test_concept_blocks_duplicate():
    doc = concept()
    doc["units"]["USD"].append(doc["units"]["USD"][0])
    with pytest.raises(ValueError, match="SEC_CONCEPT_AMBIGUOUS"):
        extract_concept(json.dumps(doc).encode())
