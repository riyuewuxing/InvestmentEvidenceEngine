import pytest

from investment_evidence_engine.issuer_q3_pressure import ROWS, extract_pressure


def pages():
    p = {5: "合并资产负债表2026年09月30日期初余额(已重述)",
         6: "", 7: "", 9: "合并年初到报告期末现金流量表本期发生额上期发生额", 10: ""}
    for page, label, a, b in ROWS.values():
        label = label.split(")")[-1]
        p[page] += "\n" + label + " " + a + " " + b
    return p


def test_reconciliation():
    out = extract_pressure(pages())
    assert out["reconciliation"] == "MATCH"
    assert out["periods"][0]["ocf_cash_capex_proxy"] == "-1200955306.02"
    assert out["periods"][1]["ocf_cash_capex_proxy"] == "-562895671.83"
    assert not out["decision_authority"]


def test_wrong_scope_or_number():
    p = pages()
    p[9] = ""
    with pytest.raises(ValueError, match="FLOW_SCOPE"):
        extract_pressure(p)
    p = pages()
    p[10] = p[10].replace("504,959,757.35", "504,959,757.36")
    with pytest.raises(ValueError, match="ROW_MISMATCH"):
        extract_pressure(p)
