from investment_evidence_engine.csrc_regional_roster_control import extract_roster, summarize


def test_roster_cell_not_contact():
    html = "<table><tr><td>1</td><td>company</td><td>000001.SZ</td><td>600000.SH</td></tr></table>"
    assert extract_roster(html) == ([(1, "000001.SZ")], 0)
    report = summarize(html)
    assert report["status"] == "BLOCK"
    assert report["count_by_exchange"] == {"SZ": 1}
    assert report["pit_safe"] is False


def test_invalid_code_and_duplicate_sequence_block():
    html = "<tr><td>1</td><td>company</td><td>bad</td></tr><tr><td>1</td><td>co</td><td>000001.SZ</td></tr>"
    assert extract_roster(html) == ([(1, "000001.SZ")], 1)
    assert summarize(html)["status"] == "BLOCK"
