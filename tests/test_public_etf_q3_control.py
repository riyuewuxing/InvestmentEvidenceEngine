"""Synthetic text schema tests; live PDFs are observed separately."""
import pytest

from investment_evidence_engine.public_etf_q3_control import DOCS, parse_pages


def pages_fixture(symbol):
    doc = DOCS[symbol]
    cover = doc["title"] + "2026 年第 3 季度报告 2026 年 9 月 30 日 报告送出日期：" + doc["cover_date"]
    notice = "本报告中财务资料未经审计。本报告期自2026年07月01日起至2026年09月30日止。"
    overview = ("基金主代码" + symbol + " 基金运作方式交易型开放式 报告期末基金份额总额1,000.00份"
                "业绩比较基准沪深300指数收益率 风险收益特征")
    financial = ("3.1 主要财务指标 1.本期已实现收益10.00 2.本期利润-3.00 "
                 "3.加权平均基金份额本期利润-0.001 4.期末基金资产净值1,000.01 "
                 "5.期末基金份额净值1.0000 注：本期利润为本期已实现收益加上变动")
    perf = ("3.2 基金净值表现 3.2.1 基金份额净值增长率及其与同期业绩比较基准收益率的比较 "
            + " ".join(k + "-10.00% 1.10% -11.00% 1.20% 1.00% -0.10%"
                       for k in ("过去三个月", "过去六个月", "过去一年"))
            + " 3.2.2 自基金合同生效以来")
    shares = ("报告期期初基金份额总额900.00 报告期间基金总申购份额150.00 减：报告期间基金总赎回份额50.00 "
              "报告期间基金拆分变动份额（份额减少以“－”填列）－ 报告期期末基金份额总额1,000.00 §7")
    pages = {1: cover, 2: notice}
    for role, text in (("overview", overview), ("financial", financial), ("performance", perf), ("shares", shares)):
        i = doc[role]
        pages[i] = pages.get(i, "") + " " + text
    return pages


@pytest.mark.parametrize("symbol", ["510330", "510320"])
def test_fixed_report_extraction_schema(symbol):
    report = parse_pages(symbol, pages_fixture(symbol))
    assert report["symbol"] == symbol
    assert report["end_nav_cny"] == "1.0000"
    assert report["split_units_label"] == "DASH"
    assert report["profit_cny"] == "-3.00"
    assert report["performance"]["3M"]["return_difference_pp"] == "1.00"


@pytest.mark.parametrize("old,new", [("基金主代码510320", "基金主代码510321"),
                                    ("本报告期自2026年07月01日", "本报告期自2026年08月01日"),
                                    ("期末基金份额净值1.0000", "期末基金份额净值1.0001"),
                                    ("报告期间基金总申购份额150.00", "报告期间基金总申购份额151.00"),
                                    ("过去三个月", "过去两个月")])
def test_identity_period_row_and_arithmetic_conflicts(old, new):
    pages = {k: v.replace(old, new) for k, v in pages_fixture("510320").items()}
    with pytest.raises(ValueError):
        parse_pages("510320", pages)
