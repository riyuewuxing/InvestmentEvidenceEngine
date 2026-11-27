import pytest

from investment_evidence_engine.public_fund_identity_control import parse_summary


def test_fixed_index_etf_requires_strategy_and_fee_anchors():
    first = ("华泰柏瑞沪深300交易型开放式指数证券投资基金 基金产品资料概要 产品概况 "
             "基金代码510300 基金管理人 基金经理 柳军 送出日期:2026年11月24日 "
             "上海证券交易所 2012年05月28日 2012年05月04日 主要采取完全复制法")
    strategy = "业绩比较基准沪深300指数 被动式投资策略 年化跟踪误差控制在2%以内"
    fees = "管理费0.15% 托管费0.05% 基金运作综合费率(年化)0.20%"
    out = parse_summary("510300", (first, strategy, fees))
    assert out["product_kind"] == "INDEX_ETF"
    assert out["estimated_operation_rate_pct"] == {"510300": "0.20"}
    assert out["target_not_realized_tracking_error"]
    assert not out["actual_cost_verified"] and not out["formal_admission"]
    assert not out["candidate_rank_membership_verified"]
    for wrong in ((first.replace("510300", "510330"), strategy, fees),
                  (first, strategy.replace("被动式投资策略", ""), fees),
                  (first, strategy, fees.replace("0.15%", "0.50%"))):
        with pytest.raises(ValueError):
            parse_summary("510300", wrong)


def test_feeder_not_etf_and_date_scoped_share_class_metadata():
    first = ("万家中证红利交易型开放式指数证券投资基金联接基金 基金产品资料概要 产品概况 "
             "基金代码161907 基金管理人 基金经理 杨坤 送出日期:2025年11月05日 "
             "下属基金交易代码161907 下属基金交易代码015558 基金中基金 "
             "万家中证红利指数证券投资基金(LOF) 2024年7月10日起")
    strategy = "目标ETF 中证红利指数收益率×95%+银行活期存款利率(税后)×5%"
    fees = ("管理费0.50% 托管费0.10% 目标ETF基金份额所对应资产净值不收取管理费和托管费 "
            "持有期间0.61% 持有期间0.71%")
    out = parse_summary("161907", (first, strategy, fees))
    assert out["product_kind"] == "ETF_FEEDER_FUND"
    assert out["former_kind"] == "LOF" and out["conversion_day_reported"] == "2024-07-10"
    assert out["fee_basis"] == "NAV_EXCLUDING_TARGET_ETF_ASSETS"
    assert not out["current_notice_chain_verified"]
    assert out["estimated_operation_rate_pct"]["015558"] == "0.71"
    with pytest.raises(ValueError):
        parse_summary("161907", (first, strategy, fees.replace("持有期间0.71%", "")))
