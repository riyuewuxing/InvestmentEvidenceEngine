from datetime import date
from decimal import Decimal

import pytest

from investment_evidence_engine.merger_consideration_control import (
    exact_entitlement,
    interval_state,
    mark_bridge,
    parse_conversion,
)


def test_hypothetical_exact_conversion_not_same_share_or_zero():
    assert exact_entitlement(100, Decimal("0.62")) == 62
    with pytest.raises(ValueError, match="FRACTIONAL"):
        exact_entitlement(101, Decimal("0.62"))
    r = mark_bridge(Decimal("10"), Decimal("20"))
    assert r["old_mark_cny"] == "1000"
    assert r["new_mark_cny"] == "1240"
    assert r["gross_endpoint_mark_change_pct"] == "24.000000"
    assert r["interim_value"] is None and not r["total_return_verified"]


@pytest.mark.parametrize("day,state", [
    (date(2025, 2, 6), "ANNOUNCED_HALT_NO_EXECUTION"),
    (date(2025, 3, 3), "ANNOUNCED_HALT_NO_EXECUTION"),
    (date(2025, 3, 4), "DELISTED_PENDING_CONVERSION_UNPRICED"),
    (date(2025, 3, 13), "ISSUER_REPORTED_REGISTERED_NOT_NEW_SHARE_LISTING"),
    (date(2025, 3, 17), "ANNOUNCED_NEW_SHARE_LISTING_DATE_REACHED_NOT_TRADE_PROOF"),
])
def test_transition_gap(day, state):
    assert interval_state(day) == state


def test_aggregate_issuance_distinguishes_treasury_and_financing():
    pages = [
        "证券代码：601211 公告编号：2025-028 A股换股实施结果、股份变动暨新增A股股份上市公告 "
        "本次股票上市流通日期为2025年3月17日 2025年3月4日海通证券A股股票终止上市后 "
        "股票市值无法在投资者账户总市值中体现 本次募集配套资金新增A股股份数量为626,174,076股",
        "",
        "A股换股实施股权登记日为2025年3月3日 按照1:0.62的比例转换为本公司A股股票 "
        "每1股海通证券A股股票可换取0.62股国泰君安A股股票 "
        "2025年3月13日收到中国证券登记结算有限责任公司上海分公司出具的《证券变更登记证明》 "
        "截至2025年3月13日止，国泰君安本次实际发行5,985,871,332股A股股票，"
        "原海通证券的A股换股股东以其于换股实施股",
        "权登记日持有的9,577,556,713股海通证券A股股票和海通证券持有的库存股77,074,467股"
        "按照1:0.62换股比例换取国泰君安发行的5,985,871,332股A股股票。",
        "国泰君安证券股份有限公司董事会2025年3月14日",
    ]
    r = parse_conversion(pages)
    assert r["theoretical_aggregate_conversion_shares"] == "5985871331.60"
    assert r["actual_minus_theoretical_shares"] == "0.40"
    assert not r["individual_allocation_verified"]
    pages[3] = pages[3].replace("77,074,467", "77,074,468")
    with pytest.raises(ValueError, match="FIXED_SHARE"):
        parse_conversion(pages)
