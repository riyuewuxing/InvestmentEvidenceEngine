import pytest

from investment_evidence_engine.issuer_cashflow_control import ROWS, checked_cashflow


def pages():
    one = "5、合并现金流量表 2025年度 2024年度 "
    two = ""
    for page, label, amounts in ROWS.values():
        line = label + " " + " ".join(amounts) + " "
        if page == 108:
            one += line
        else:
            two += line
    return one, two + "6、母公司现金流量表 经营活动产生的现金流量净额 61,093,686.68 119,995,966.50"


def test_cashflow_consolidated_arithmetic_and_parent_exclusion():
    out = checked_cashflow(*pages())
    assert out["cash_change_reconciled"] and out["cash_balance_reconciled"]
    assert out["years_cny"]["2025"]["operating_minus_capex_proxy"] == "-917202868.12"
    assert out["years_cny"]["2024"]["operating_minus_capex_proxy"] == "-1313367580.77"


@pytest.mark.parametrize("mode", ["parent", "missing_scope", "wrong_cell", "duplicate"])
def test_cashflow_page_scope_and_data_match(mode):
    a, b = pages()
    if mode == "parent":
        b = b.replace("母公司现金流量表", "其他")
    elif mode == "missing_scope":
        a = a.replace("合并现金流量表", "")
    elif mode == "wrong_cell":
        a = a.replace("1,570,291,924.55", "1,570,291,924.56")
    else:
        a += "经营活动产生的现金流量净额 653,089,056.43 655,318,988.92"
    with pytest.raises(ValueError):
        checked_cashflow(a, b)
