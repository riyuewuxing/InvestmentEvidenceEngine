from datetime import date

import pytest

from investment_evidence_engine.transfer_control import event_state, parse_text, pdf_declared_length

A_NOTICE = ("关于锦州港股份有限公司A股股份确权的提示性公告 2025-08-07 "
            "锦州港股份有限公司A股（证券简称：退市锦港，证券代码：600190，确权证券代码：400280）"
            "于2025年7月25日在上交所摘牌并终止上市，预计将于2025年9月26日前在退市板块挂牌转让。"
            "2025年8月15日")


def test_broker_mapping_never_infers_effective_date():
    row = parse_text("broker_a", A_NOTICE)
    assert row["confirmation_code"] == "400280"
    assert row["expected_entry_by"] == "2025-09-26"
    assert row["actual_board_entry"] is None
    assert not row["account_confirmation_verified"]


@pytest.mark.parametrize("altered", [
    A_NOTICE.replace("400280", "420280"),
    A_NOTICE.replace("600190", "900952"),
    A_NOTICE.replace("预计将于", "实际于"),
    A_NOTICE + A_NOTICE,
])
def test_wrong_mapping_or_scope_rejected(altered):
    with pytest.raises(ValueError, match="TRANSFER_BROKER_MAPPING"):
        parse_text("broker_a", altered)


def test_risk_share_counts_are_class_specific():
    value = ("锦州港股份有限公司投资风险分析 山西证券 2025年9月17日起在退市板块挂牌转让。"
             "截至2025年9月3日，公司A股股本结构如下：退市板块待确认股份 12 总股本 100 "
             "截至2025年9月3日，公司B股股本结构如下：退市板块待确认股份 34 总股本 200")
    rows = parse_text("risk", value)["share_counts"]
    assert rows == {"A": {"pending_confirmation": 12, "total": 100},
                    "B": {"pending_confirmation": 34, "total": 200}}
    with pytest.raises(ValueError):
        parse_text("risk", value.replace("34 总股本 200", "201 总股本 200"))


def test_transfer_gap_and_account_eligibility():
    assert event_state(date(2025, 7, 19), entry_verified=True) == "AFTER_DELISTING_PERIOD_BEFORE_REMOVAL"
    assert event_state(date(2025, 9, 16), entry_verified=True) == "OLD_VENUE_REMOVED_BEFORE_REPORTED_NEW_ENTRY"
    assert event_state(date(2025, 9, 17), entry_verified=True) == "NEW_VENUE_REPORTED_ACCOUNT_TRADABILITY_UNVERIFIED"
    assert event_state(date(2025, 9, 26), entry_verified=False) == "OLD_VENUE_REMOVED_NEW_VENUE_UNVERIFIED"


def test_missing_class_row_must_not_borrow_other_class():
    value = ("锦州港股份有限公司投资风险分析 山西证券 2025年9月17日起在退市板块挂牌转让。"
             "截至2025年9月3日，公司A股股本结构如下：未知 "
             "截至2025年9月3日，公司B股股本结构如下：退市板块待确认股份 34 总股本 200")
    with pytest.raises(ValueError, match="TRANSFER_RISK_PENDING_SHARES"):
        parse_text("risk", value)


def test_duplicate_class_row_and_reverse_class_order_rejected():
    value = ("锦州港股份有限公司投资风险分析 山西证券 2025年9月17日起在退市板块挂牌转让。"
             "截至2025年9月3日，公司A股股本结构如下：退市板块待确认股份 1 总股本 100 "
             "退市板块待确认股份 2 总股本 100 "
             "截至2025年9月3日，公司B股股本结构如下：退市板块待确认股份 34 总股本 200")
    with pytest.raises(ValueError, match="TRANSFER_RISK_PENDING_SHARES"):
        parse_text("risk", value)
    reversed_classes = value.replace("公司A股", "公司X股").replace("公司B股", "公司A股").replace("公司X股", "公司B股")
    with pytest.raises(ValueError, match="TRANSFER_RISK_CLASS_SCOPE"):
        parse_text("risk", reversed_classes)


@pytest.mark.parametrize("value", [None, "", "0", "-1", "abc", "4194304", "8388609", "9999999999999"])
def test_pdf_size_probe_denies_ambiguous_or_out_of_range_metadata(value):
    assert pdf_declared_length(value) is None


def test_pdf_size_probe_only_allows_new_bounded_size():
    assert pdf_declared_length("4194305") == 4194305
    assert pdf_declared_length("8388608") == 8388608
