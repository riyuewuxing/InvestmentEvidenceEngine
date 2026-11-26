import json
from datetime import date

import pytest

from investment_evidence_engine.delisting_directory import summarize


def body(rows, total=None):
    return json.dumps({"result": rows, "pageHelp": {"total": len(rows) if total is None else total}}).encode()


def row(code, end, start="1999-01-01", a=None):
    return {"COMPANY_CODE": code, "A_STOCK_CODE": a, "LIST_DATE": start, "DELIST_DATE": end}


def test_delisted_survivor_scope_and_exact_date():
    raw = body([row("600462", "2025-07-21", a="600462"), row("600190", "2025-07-18"),
                row("900952", "2025-07-25"), row("600837", "2025-03-04"),
                row("600001", None), row("600002", "2026-12-01")])
    result = summarize(raw, "sse_delisted", date(2026, 11, 26))
    assert result["valid_a_prefix_intervals"] == 3
    assert result["retrospective_interval_membership_counts"]["2024-12-31"] == 3
    assert result["retrospective_interval_membership_counts"]["2025-12-31"] == 0
    assert result["anchors"]["600190"]["status"] == "DIFFERENT_DATE_SEMANTICS"
    assert result["anchors"]["600462"]["status"] == "MATCH"
    assert result["excluded"] == {"non_a_prefix_or_unknown": 1, "missing_or_invalid_interval": 2}
    assert not result["pit_safe"]


def test_directory_truncation_and_duplicate_block():
    r = row("600462", "2025-07-21")
    with pytest.raises(ValueError, match="TRUNCATED"):
        summarize(body([r], total=2), "sse_delisted", date(2026, 11, 26))
    with pytest.raises(ValueError, match="NO_VALID_INTERVALS"):
        summarize(body([r, r]), "sse_delisted", date(2026, 11, 26))
    result = summarize(body([r, r, row("600837", "2025-03-04")]),
                       "sse_delisted", date(2026, 11, 26))
    assert result["ambiguous_duplicate_directory_keys"] == 1
    assert result["excluded"]["ambiguous_duplicate_key_rows"] == 2
    assert result["valid_a_prefix_intervals"] == 1
    assert result["anchors"]["600462"]["status"] == "ABSENT_OR_EXCLUDED"


def test_xlsx_a_b_identity_separate():
    import io

    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["证券代码", "证券简称", "上市日期", "终止上市日期"])
    sheet.append([16, "A", "1992-03-27", "2026-10-23"])
    sheet.append(["200016", "B", "1992-03-27", "2026-10-23"])
    b = io.BytesIO()
    book.save(b)
    r = summarize(b.getvalue(), "szse_delisted", date(2026, 11, 26))
    assert r["valid_a_prefix_intervals"] == 1
    assert r["anchors"]["000016"]["status"] == "MATCH"
    assert r["excluded"]["non_a_prefix_or_unknown"] == 1
