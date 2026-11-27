import pytest

from investment_evidence_engine.public_fund_dealing_control import parse_notice

HOLIDAY = ("嘉实中证海外中国互联网30交易型开放式指数证券投资基金(QDII) "
           "基金主代码159607 嘉实基金管理有限公司 公告送出日期:2026年9月3日 "
           "暂停申购起始日2026年9月7日 暂停赎回起始日2026年9月7日 "
           "2026年9月7日纽约证券交易所、纳斯达克证券交易所休市 "
           "恢复申购日2026年9月8日 恢复赎回日2026年9月8日 "
           "投资者在2026年9月7日仍可进行本基金的二级市场交易 "
           "2026年9月8日起(含2026年9月8日)恢复本基金的日常申购、赎回业务")
HALT = ("易方达纳斯达克100交易型开放式指数证券投资基金(QDII) "
        "基金代码:159696 二级市场交易价格溢价风险提示及停复牌公告 "
        "2026年8月27日 收盘价为2.044元 收盘时基金份额参考净值(IOPV)为1.8392元 "
        "2026年8月28日开市起停牌 2026年8月28日10:30起复牌 "
        "停牌期间本基金赎回业务照常办理 实际申赎状态请以最新公告为准 易方达基金管理有限公司")
CAP = ("万家中证红利交易型开放式指数证券投资基金联接基金 基金主代码161907 "
       "万家基金管理有限公司 下属分级基金的交易代码161907015558 "
       "公告送出日期:2026年8月10日 "
       "暂停大额申购(含转换转入、定期定额投资)起始日2026年8月11日 "
       "该分级基金暂停大额申购(含转换转入、定期定额投资)金额100万元100万元")
CAP_TERMS = ("A类及C类份额单日申购金额合并计算不超过100万元 "
             "所有销售机构(包括代销及直销渠道) 单日单个基金账户单笔或多笔累计 "
             "限额为100万元(不含100万元) 对超过100万元部分的申请基金管理人有权拒绝 "
             "赎回及转换转出等业务正常办理 具体时间将另行公告")


def test_holiday_and_halt_are_distinct_channel_observations():
    holiday = parse_notice("holiday", (HOLIDAY,))
    halt = parse_notice("halt", (HALT,))
    assert holiday["primary_subscription"] == holiday["primary_redemption"] == "SUSPENDED"
    assert holiday["secondary_trading"] == "REPORTED_ALLOWED"
    assert halt["secondary_trading_during_halt"] == "SUSPENDED"
    assert halt["primary_redemption_during_halt"] == "REPORTED_ALLOWED"
    assert halt["primary_subscription_during_halt"] == "UNKNOWN"
    assert not halt["actual_resume_verified"]
    assert float(halt["reported_close_iopv_premium_pct"]) == pytest.approx((2.044 / 1.8392 - 1) * 100)


def test_combined_cap_is_not_separate_per_class_or_inclusive_at_boundary():
    result = parse_notice("cap", (CAP, CAP_TERMS))
    assert result["share_class_codes"] == ["161907", "015558"]
    assert result["reported_cap_cny"] == "1000000"
    assert result["at_exact_cap"] == "AMBIGUOUS_SOURCE_WORDING"
    assert result["resume_session"] is None
    assert not result["actual_acceptance_verified"]


@pytest.mark.parametrize("key,pages,old,new", [
    ("holiday", (HOLIDAY,), "159607", "159608"),
    ("holiday", (HOLIDAY,), "暂停赎回起始日2026年9月7日", "暂停赎回起始日2026年9月8日"),
    ("halt", (HALT,), "10:30起复牌", "11:30起复牌"),
    ("halt", (HALT,), "1.8392", "1.8393"),
    ("cap", (CAP, CAP_TERMS), "单日申购金额合并计算", "单日分别计算"),
    ("cap", (CAP, CAP_TERMS), "不含100万元", "含100万元"),
])
def test_scope_changes_fail_closed(key, pages, old, new):
    with pytest.raises(ValueError, match="FUND_DEALING_REVIEWED_ANCHORS"):
        parse_notice(key, tuple(p.replace(old, new) for p in pages))


def test_earlier_cap_release_not_current_open():
    raw = ("万家中证红利交易型开放式指数证券投资基金联接基金 基金主代码161907 "
           "万家基金管理有限公司 下属分级基金的交易代码161907015558 "
           "公告送出日期:2026年5月18日 恢复大额申购(含转换转入、定期定额投资)起始日2026年5月18日 "
           "取消对本基金单日单个基金账户单笔或多笔累计金额100万元以上的大额申购(含转换转入、定期定额投资)申请的限制")
    result = parse_notice("earlier_release", (raw,))
    assert result["specific_previous_cap_removed"]
    assert not result["all_other_limits_absent_verified"]
    assert not result["complete_notice_chain_verified"]
