import pytest

from investment_evidence_engine.issuer_q3_control import ROWS, extract_q3, observe_pdf


def pages():
    first = "中国天楹股份有限公司2026年第三季度报告000035 TY2026-54 会计政策变更 调整前 调整后 "
    percentages = {"revenue": ("-6.18%", "0.16%"), "parent_profit": ("-25.22%", "-7.00%"),
                   "adjusted_profit": ("-28.78%", "1.10%")}
    for key, (label, vals) in ROWS.items():
        first += label+"（元）"+" ".join(vals[:3])+" "+percentages[key][0]+" "
        first += " ".join(vals[3:])+" "+percentages[key][1]+" "
    return first, "TY2026-22 2026年1月1日 调整前 调整后"


def test_q3_restated_comparative_basis():
    result = extract_q3(*pages())
    assert result["rows_cny"]["parent_profit"]["ytd_yoy_pct"] == "-7.00"
    assert result["rows_cny"]["revenue"]["ytd_yoy_pct"] == "0.16"
    assert not result["historical_vintage_verified"]


def test_q3_rejects_mismatched_value_or_policy():
    a, b = pages()
    for text, policy in [(a.replace("70,233,534.70", "70,233,534.71"), b),
                         (a.replace("-7.00%", "-6.99%"), b), (a, "")]:
        with pytest.raises(ValueError):
            extract_q3(text, policy)


def test_q3_rejects_unapproved_url(tmp_path):
    assert observe_pdf("https://example.com/report.pdf", tmp_path)["error"] == "Q3_URL_SCOPE"
