from investment_evidence_engine.bse_2024_roster_reconciliation import (
    parse_ipo,
    parse_mapping,
    reconcile,
)


def test_parse_and_keep_new_code_distinct_from_legacy():
    mapping = parse_mapping("  1  example  2024-03-29  837023  920123")
    ipo = parse_ipo("  1  920116  X  2750  6.92  1.90  A  2024/12/24  2024/12/27  2025/1/2\n"
                    "  2  837023  X  800  5.77  0.46  A  2024/3/20  2024/3/25  2024/3/29")
    assert mapping == [(1, "2024-03-29", "837023", "920123")]
    assert ipo == [(1, "920116", "2025-01-02"), (2, "837023", "2024-03-29")]
    report = reconcile(mapping, ipo)
    assert report["status"] == "BLOCK"
    assert report["same_legacy_2024_code_date_set"]
    assert report["candidate_2024_year_end_count"] == 1
    assert report["after_cutoff_excluded"] == [("920116", "2025-01-02")]
    assert not report["pit_safe"]


def test_notice_does_not_backdate_mapping_or_cutover():
    from investment_evidence_engine.bse_2024_roster_reconciliation import parse_notice_text

    text = ("关于做好北京证券交易所存量上市公司证券代码切换准备工作的通知\n"
            "2024-12-13 北证公告〔2024〕231号\n"
            "2024年4月22日起为新增上市公司普通股票启用920代码号段\n"
            "存量上市公司股票新旧代码对照表 股票代码重复的 第四位代码做递进处理\n"
            "具体事宜本所将另行通知")
    result = parse_notice_text(text)
    assert result["status"] == "WARN"
    assert not result["historical_availability_verified"]
    assert not result["exact_attachment_version_at_publication_verified"]
    assert parse_notice_text(text.replace("231号", "232号"))["status"] == "BLOCK"
