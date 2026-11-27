import pytest

from investment_evidence_engine.public_symbol_change_control import (
    normalize_window,
    parse_reviewed_notice,
    summarize_vendor_windows,
)


def test_notice_explicit_old_new_date_and_continuity():
    pages = ("公告编号：2025-028 关于变更公司证券简称及证券代码的实施公告 深圳证券交易所创业板股票上市规则 "
             "2025年2月17日开市起启用变更后的证券简称及证券代码 变更后的证券代码：302132 公司法人主体存续",
             "证券代码 300114 302132 2025年2月17日 证券类别和持有数量与代码变更完成前一致 本次重大资产重组已实施完成")
    result = parse_reviewed_notice(pages)
    assert result["old_symbol"] == "300114"
    assert result["new_symbol"] == "302132"
    assert result["effective_session"] == "2025-02-17"
    assert result["automatic_price_stitch_allowed"] is False
    with pytest.raises(ValueError):
        parse_reviewed_notice((pages[0], pages[1].replace("300114", "300115")))


def test_cross_code_overlap_reported_never_stitched():
    old = normalize_window([["2025-02-14", "30.10"], ["2025-02-17", 31]])
    new = normalize_window([["2025-02-14", 30.1], ["2025-02-17", 31.01]])
    r = summarize_vendor_windows(old, new)
    assert r["overlap_sessions"] == 2 and r["overlap_equal_closes"] == 1
    assert r["old_request"]["post_change_rows"] == 1
    assert r["new_request"]["pre_change_rows"] == 1
    assert r["automatic_price_stitch_allowed"] is False
    assert r["decision_authority"] is False


def test_empty_and_unavailable_not_conflated():
    r = summarize_vendor_windows({}, None)
    assert r["old_request"]["status"] == "EMPTY_RESPONSE"
    assert r["new_request"]["status"] == "UNAVAILABLE"
    assert "overlap_sessions" not in r


@pytest.mark.parametrize("rows", [
    [["2025-02-08", 1]], [["2025-02-15", 1]], [["2025-02-22", 1]],
    [["2025-02-14", 1], ["2025-02-14", 2]], [["2025-02-14", True]],
    [["2025-02-14", "NaN"]], [["2025-02-14", "0"]], [["2025-02-14", "-1"]],
])
def test_bad_window_blocked(rows):
    with pytest.raises(ValueError):
        normalize_window(rows)
