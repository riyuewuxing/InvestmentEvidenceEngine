import json

import pytest

from investment_evidence_engine.szse_coverage_probe import monthly_fields, page_fields


def test_monthly_count_is_not_security_universe():
    text = "<h1>市场总貌 MARKET OVERVIEW – (2026.10)</h1><table><tr><td>上市公司数目</td><td>No. of Listed Companies</td><td>2908</td></tr><tr><td>创业板</td><td>ChiNext</td><td>1411</td></tr><tr><td>上市证券数目</td></tr></table>"
    result = monthly_fields(text.encode(), "utf-8")
    assert result["non_chinext_company_count_derived"] == 1497
    assert not result["current_code_universe_verified"]
    with pytest.raises(ValueError, match="IDENTITY"):
        monthly_fields(text.replace("2026.10", "2026.09").encode(), "utf-8")


def test_first_page_cannot_certify_completeness():
    data = [{"data": [{"agdm": "000001"}], "metadata": {"pagecount": 146}}]
    assert not page_fields(json.dumps(data).encode())["current_code_universe_verified"]
    data[0]["data"].append({"agdm": "000001"})
    with pytest.raises(ValueError, match="DUPLICATE"):
        page_fields(json.dumps(data).encode())
