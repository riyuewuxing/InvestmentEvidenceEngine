import pytest

from investment_evidence_engine.public_relisting_issuer_control import parse_notice

PAGES = (
    "证券代码：601975 公告编号：临2018-089 关于公司股票重新上市的公告 2019年1月8日 "
    "重新上市首日，公司股票价格不设涨跌幅限制 最后交易日（2017年2月27日）的收盘价，即4.31元/股 "
    "重新上市次日起，公司股票价格的日涨跌幅限制为5%",
    "无限售条件流通股 1,898,551,957 37.79 有限售条件流通股 3,124,848,067 62.21 总股本 5,023,400,024 100.00",
    "最后交易日（2017年2月27日）的收盘价，即4.31元/股 首日不设涨跌幅限制",
    "中国长江航运集团南京油运股份有限公司 董事会 二〇一八年十二月十八日",
)


def test_issuer_notice_reconciles_share_table_and_provenance():
    result = parse_notice(PAGES)
    assert result["share_table_reconciled"] is True
    assert result["unrestricted_share_pct_rounded"] == "37.79"
    assert result["restricted_share_pct_rounded"] == "62.21"
    assert result["opening_reference_source_session"] == "2017-02-27"
    assert result["opening_reference_cny"] == "4.31"
    assert result["opening_reference_is_executed_open"] is False
    assert result["document_signature_date"] == "2018-12-18"
    assert result["archive_path_date"] == "2018-12-28"
    assert result["historical_first_availability_verified"] is False


@pytest.mark.parametrize("index,old,new", [
    (0, "601975", "601976"),
    (1, "3,124,848,067", "3,124,848,068"),
    (2, "4.31", "4.32"),
    (3, "董事会", "其他部门"),
])
def test_issuer_notice_blocks_wrong_identity_or_terms(index, old, new):
    changed = list(PAGES)
    changed[index] = changed[index].replace(old, new)
    with pytest.raises(ValueError):
        parse_notice(tuple(changed))
