import pytest

from investment_evidence_engine.issuer_cashflow_control import Q1_ROWS, checked_q1_adjustments


def pages():
    header = "中国天楹股份有限公司 2026 年第一季度报告\n"
    out = {11: header + "2026年起首次执行新会计准则 2025年12月31日（经审计） 2026年1月1日（未经审计） 调整数",
           12: header, 14: header}
    for page, label, cells in Q1_ROWS.values():
        out[page] += "\n" + label + " " + " ".join(cells)
    return out[11], out[12], out[14]


def test_q1_counterexample_exact_balances_not_historical_availability():
    result = checked_q1_adjustments(*pages())
    assert result["balance_reconciled"]
    assert result["same_adjusted_values_as_half_2026"]
    assert not result["first_availability_verified"]
    assert not result["same_day_order_verified"]
    assert result["rows_cny"]["parent_equity"][2] == "-134432992.12"


@pytest.mark.parametrize("bad", ["未经审计", "32,067,826,798.82", "117,918,407.76"])
def test_q1_rejects_changed_scope_or_cell(bad):
    with pytest.raises(ValueError):
        checked_q1_adjustments(*(page.replace(bad, "UNKNOWN") for page in pages()))
