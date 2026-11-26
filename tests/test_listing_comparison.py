import pytest

from investment_evidence_engine.listing_comparison import (
    compare_code_sets,
    normalize_codes,
    stock_code,
)


@pytest.mark.parametrize(("raw", "expected"), [
    ("sh.000001", None), ("sz.000001", "sz.000001"), ("sh600519", "sh.600519"),
    ("sz399001", None), ("bj.920001", None), ("sh.510050", None),
    ("000001", "sz.000001"), ("600519", "sh.600519"),
])
def test_exchange_aware_scope(raw, expected):
    assert stock_code(raw, require_exchange=False) == expected


@pytest.mark.parametrize("raw", ["600519", "sh.60051", 600519, "sh.６００５１９"])
def test_reference_requires_exact_exchange_code(raw):
    with pytest.raises(ValueError):
        stock_code(raw, require_exchange=True)


def test_duplicate_and_invalid_codes_do_not_silently_match():
    result = compare_code_sets(["sh.600519", "sh.600519", "sz.000001"], ["600519", "000001"])
    assert result["status"] == "BLOCK_INCOMPLETE_OR_AMBIGUOUS"
    assert result["reference"]["duplicate_count"] == 1
    assert result["overlap"] == 2
    assert not result["decision_authority"]


def test_large_matching_sets_are_not_formal_coverage():
    left = [f"sh.600{i:03d}" for i in range(1000)] + [f"sz.000{i:03d}" for i in range(1000)]
    right = [item[3:] for item in reversed(left)]
    result = compare_code_sets(left, right)
    assert result["status"] == "MATCH_OBSERVED_SETS"
    assert result["overlap"] == 2000
    assert result["reference"]["normalized_code_set_sha256"] == result["snapshot"]["normalized_code_set_sha256"]
    for flag in ("listing_completeness_verified", "quote_trade_date_verified",
                 "source_independence_verified", "historical_vintage_verified"):
        assert result[flag] is False
    right[-1] = "601999"
    result = compare_code_sets(left, right)
    assert result["status"] == "DIFFERENT_OBSERVED_SETS"
    assert result["reference_only"] == result["snapshot_only"] == 1


def test_unknown_or_invalid_records_counted():
    _, stats = normalize_codes(["sh.000001", "bad", "sh.600519"], require_exchange=True)
    assert stats["out_of_scope_count"] == 1
    assert stats["invalid_count"] == 1
