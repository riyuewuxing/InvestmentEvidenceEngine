import pytest

from investment_evidence_engine.public_current_share_proxy import parse_share_count, proxy


def test_share_proxy_requires_dated_exact_anchor():
    with pytest.raises(ValueError):
        parse_share_count(("证券代码:000035 中国天楹股份有限公司 2,388,032,769股",))
    row = proxy(2388032769)
    assert row["share_count_as_of"] == "2026-10-30"
    assert row["conditional_capitalization_cny"] == "9432729437.55"
    assert not row["current_share_count_verified"]
    assert not row["decision_authority"]


def test_share_proxy_does_not_guess_share_count():
    with pytest.raises(ValueError):
        proxy(2388032770)
