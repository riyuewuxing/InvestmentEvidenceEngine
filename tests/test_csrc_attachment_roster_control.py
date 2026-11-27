from investment_evidence_engine.csrc_attachment_roster_control import (
    board_candidate,
    fixed_urls,
    normalize_code,
)


def test_code_normalization_never_guesses_lost_leading_zeros():
    assert normalize_code("000001.SZ", "General") == "000001.SZ"
    assert normalize_code(1, "000000") == "000001"
    assert normalize_code(1, "General") is None
    assert normalize_code("1", "General") is None
    assert normalize_code(True, "000000") is None
    assert board_candidate("000001.SH") == "SUFFIX_CONFLICT"
    assert board_candidate("689009") == "SH_STAR"
    assert board_candidate("830896.BJ") == "BJ_CANDIDATE"


def test_exact_official_attachment_path():
    page, attachment = fixed_urls("shenzhen")
    assert page.endswith("/c7535610/content.shtml")
    assert "/c7535610/7535610/files/" in attachment
    assert normalize_code(600000, "General") == "600000"


def test_empty_sheet_not_invented_and_exact_disjoint_partition():
    import io

    from openpyxl import Workbook

    from investment_evidence_engine.csrc_attachment_roster_control import summarize_workbook

    book = Workbook()
    book.active.append(["证券代码"])
    book.active.append(["600000.SH"])
    book.active.append(["000001.SZ"])
    book.create_sheet("blank")
    sh = book.create_sheet("sh")
    sh.append(["股票代码"])
    sh.append(["600000.SH"])
    sz = book.create_sheet("sz")
    sz.append(["股票代码"])
    sz.append(["000001.SZ"])
    raw = io.BytesIO()
    book.save(raw)
    result = summarize_workbook(raw.getvalue())
    assert result["status"] == "WARN"
    assert result["sheets"][1]["status"] == "EMPTY"
    assert result["partition_check"]["union_equals_total"]
    book["blank"].append(["unidentified nonempty sheet"])
    raw = io.BytesIO()
    book.save(raw)
    assert summarize_workbook(raw.getvalue())["status"] == "BLOCK"
