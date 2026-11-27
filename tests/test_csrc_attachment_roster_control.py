from investment_evidence_engine.csrc_attachment_roster_control import (
    board_candidate,
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
