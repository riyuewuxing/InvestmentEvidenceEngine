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
