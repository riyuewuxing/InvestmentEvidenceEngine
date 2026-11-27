from investment_evidence_engine.sse_factbook_control import (
    board,
    candidate_membership,
    directory_crosscheck,
    parse_rows,
    summarize,
)


def test_annual_trading_rows_not_automatically_year_end_members():
    rows, bad = parse_rows(
        " 600000  Foo  123.45  12.34  56.78  56.78  1.000\n"
        " 689009  Bar  0.00  0.00  56.78  56.78  1.000\n"
        " 900901  Foo B  —  —  12.34  12.34  1.000\n"
        " 600001  malformed"
    )
    assert bad == 1
    assert rows == [("600000", "123.45"), ("689009", "0.00"), ("900901", "—")]
    result = summarize(rows + [rows[0]], bad)
    assert result["duplicate_code_count"] == 1
    assert result["boards"]["main_a"]["unique"] == 1
    assert result["boards"]["star"]["nonpositive_codes"] == ["689009"]
    assert result["boards"]["main_b"]["nonpositive_codes"] == ["900901"]
    assert not result["complete_historical_universe_verified"]
    assert not result["pit_safe"]
    assert board("689009") == "star"
    assert board("699999") == "unknown"


def test_pdf_decimal_whitespace_does_not_shift_market_value():
    rows, rejected = parse_rows("  600000    Example    302033.  91    302033. 91    29352. 18    29352. 18    6.620    6. 630    11. 020    6.360")
    assert rows == [("600000", "302033.91")]
    assert rejected == 0


def test_candidate_does_not_admit_partial_company_coverage():
    result = candidate_membership([("600112", "5.00"), ("689009", "2.00")], ["689009"])
    assert result["status"] == "BLOCK"
    assert result["same_company_a_set"]
    assert result["ordinary_a_candidate_count"] == 0
    assert result["excluded_codes_present"] == ["600112"]


def test_directory_missing_targets_not_promoted():
    import json

    body = json.dumps({"pageHelp": {"total": 1}, "result": [{"COMPANY_CODE": "900953", "B_STOCK_CODE": "900953", "DELIST_DATE": "2024-07-05"}]}).encode()
    result = directory_crosscheck(body)
    assert result["matched_count"] == 1
    assert result["targets"]["900953"]["identity_basis"] == "B_STOCK_CODE"
    assert result["status"] == "BLOCK"
