from datetime import date

from investment_evidence_engine.public_industry_coverage import analyze, normalize, windows


def record(code, day, close, name="示例行业"):
    return {"指数代码": code, "发布日期": day, "收盘指数": close, "指数名称": name}


def test_industry_only_common_dated_valid_close_and_no_identity_mixing():
    w = windows(date(2026, 11, 27))
    recent = normalize([record("801010", "2026-11-26", 90), record("801020", "2026-11-26", 110),
                        record("801030", "2026-11-27", 100)], *w["recent"])
    month = normalize([record("801010", "2026-10-27", 80), record("801020", "2026-10-27", 100)],
                      *w["month"])
    year = normalize([record("801010", "2025-11-27", 100), record("801020", "2025-11-27", 130, "不同名称")],
                     *w["year"])
    out = analyze({"recent": recent, "month": month, "year": year}, w)
    assert out["windows"]["recent"]["selected_day"] == "2026-11-26"
    assert out["recent_scope_count"] == 2
    assert out["common_identity_complete_count"] == 1
    assert out["identity_mismatch_count"] == 1
    assert out["match_count"] == 1
    assert out["research_candidates"][0]["code"] == "801010"
    assert out["research_candidates"][0]["short_price_return_pct"] == 12.5
    assert not out["formal_pit"] and not out["expectation_gap_verified"]


def test_missing_window_blocks_and_duplicates_not_guessed():
    w = windows(date(2026, 11, 27))
    recent = normalize([record("801010", "2026-11-26", 90), record("801010", "2026-11-26", 91),
                        record("801020", "2026-11-26", 0), record("801030", "2026-11-28", 1)],
                       *w["recent"])
    assert recent["ambiguous_duplicate_rows"] == 2
    assert recent["invalid_count"] == 1
    out = analyze({"recent": recent}, w)
    assert out["status"] == "BLOCK_INCOMPLETE"
    assert out["match_count"] is None and out["common_identity_complete_count"] is None
