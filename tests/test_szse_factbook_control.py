from investment_evidence_engine.szse_factbook_control import parse_rows, summarize_rows


def test_two_columns_are_separate_and_codes_keep_leading_zero():
    text = " 1 000858 五 粮 液 543 580.39 2.6404 2.6404 000001 平安银行 227 045.19 1.2254 1.2254\n"
    text += " 2 000001 平安银行 227 049.24 1.1029 3.7433 000858 五 粮 液 123 456.78 0.1234 1.3488\n"
    rows, bad = parse_rows(text)
    assert bad == 0 and len(rows) == 2
    assert rows[0] == (1, "000858", "000001", "543580.39", "227045.19")
    result = summarize_rows(rows, "main", bad)
    assert result["status"] == "RANKING_RECONCILED_ONLY"
    assert result["same_code_sets"] and not result["historical_universe_complete"]
    assert result["count_difference"] == 2-1521


def test_incomplete_duplicate_or_wrong_board_does_not_pass():
    rows, bad = parse_rows(" 1 000858 五粮液 12.00 1.0000 1.0000 300750 宁德时代 10.00 1.0000 1.0000\n"
                           " 2 000858 broken")
    assert bad == 1
    assert summarize_rows(rows, "main", bad)["status"] == "BLOCK"
    assert summarize_rows(rows*2, "main", 0)["status"] == "BLOCK"
