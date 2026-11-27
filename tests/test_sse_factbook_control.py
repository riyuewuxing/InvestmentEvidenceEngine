from investment_evidence_engine.sse_factbook_control import board, parse_rows, summarize


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
