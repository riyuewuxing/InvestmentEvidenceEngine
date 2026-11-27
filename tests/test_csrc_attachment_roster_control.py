from investment_evidence_engine.csrc_attachment_roster_control import (
    board_candidate,
    fixed_urls,
    normalize_code,
    prior_jiangxi_version,
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


def test_timeout_without_bytes_is_not_a_changed_version():
    assert prior_jiangxi_version({"worker_status": "WATCHDOG_TIMEOUT"}) == "NOT_OBSERVED"
    assert prior_jiangxi_version({"page_sha256": "abc", "attachment_sha256": "def"}) == "MISMATCH"
    assert prior_jiangxi_version({"page_sha256": "b0e343022fd7edabe8ac56bf96aa5827a834e7e2161296ed19ce843a20e786e7",
                                 "attachment_sha256": "a0133a28f6a3bcba3c3e056f29767f83436b8db1c6964cbd977924c99e6135c6"}) == "MATCH"
