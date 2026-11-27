import pytest

from investment_evidence_engine.public_relisting_control import (
    NOTICES,
    describe_rows,
    normalize_window,
    parse_notice,
)


@pytest.mark.parametrize("key", list(NOTICES))
def test_reviewed_notice_requires_every_anchor(key):
    _, label, title, anchors = NOTICES[key]
    body = ("<html>" + title + " " + label + " 上海证券交易所 " + " ".join(anchors) + "</html>").encode()
    result = parse_notice(body, key)
    assert result["declared_notice_date"] == label
    assert result["historical_first_availability_verified"] is False
    with pytest.raises(ValueError, match="RELIST_NOTICE_REVIEWED_FIELDS_MISMATCH"):
        parse_notice(body.replace(anchors[-1].encode(), b"absent"), key)
    # Hidden script content may not satisfy a required visible anchor.
    with pytest.raises(ValueError):
        parse_notice(body.replace(anchors[-1].encode(), b"<script>" + anchors[-1].encode() + b"</script>"), key)


def test_distinct_listing_and_intraday_notice():
    for key, field, expected in (
        ("removal", "removal", "2014-06-05"),
        ("approval", "otc_code", "400061"),
        ("relisting", "admitted_on_first_day_shares", 1898551957),
        ("halt", "resume", "2019-01-08T14:57:00+08:00"),
    ):
        _, label, title, anchors = NOTICES[key]
        raw = (title + " " + label + " 上海证券交易所 " + " ".join(anchors)).encode()
        assert parse_notice(raw, key)[field] == expected


def test_vendor_rows_are_diagnostics_not_tradability():
    rows = normalize_window([["2019-01-07", "3.50"], ["2019-01-08", 3.5]], "relisting")
    out = describe_rows(rows, "relisting", "601975")
    assert out["incompatible_with_reported_sse_listing_dates"] == ["2019-01-07"]
    assert out["historical_tradability_verified"] is False
    assert describe_rows(rows, "relisting", "600087")["incompatible_with_reported_sse_listing_dates"] == list(rows)
    assert describe_rows({}, "relisting", "601975")["status"] == "EMPTY_RESPONSE"


@pytest.mark.parametrize("rows", [
    [["2019-01-05", 1]], [["2019-01-12", 1]], [["2019-01-07", True]],
    [["2019-01-07", "NaN"]], [["2019-01-07", 0]],
    [["2019-01-07", 1], ["2019-01-07", 2]],
])
def test_invalid_vendor_rows_rejected(rows):
    with pytest.raises(ValueError):
        normalize_window(rows, "relisting")

def test_supplement_distinguishes_share_surrender_and_first_day_limit():
    _, label, title, anchors = NOTICES["relisting_education"]
    raw = (title + " " + label + " 上海证券交易所 " + " ".join(anchors)).encode()
    fields = parse_notice(raw, "relisting_education")
    assert fields["first_session_daily_limit"] == "NONE"
    assert fields["reorganization_reported_share_surrender_pct"] == {
        "named_shareholder": 50, "other_small_shareholders": 10,
    }
    assert len(fields["reported_halts"]) == 2
    assert fields["individual_entitlement_verified"] is False


def test_partial_supplement_keeps_case_observation_without_admitting_rule_chain(monkeypatch):
    from investment_evidence_engine import public_relisting_control as module

    def observe(kind, key):
        return {"status": "OBSERVED" if key == "relisting_education" else "BLOCK"}

    monkeypatch.setattr(module, "observe", observe)
    result = module.run_supplement()
    assert result["status"] == "BLOCK"
    assert result["ordinary_st_rule_invalid_on_reviewed_first_session"] is True
    assert result["price_only_continuity_is_insufficient_for_shareholder_return"] is True
    assert result["historical_rule_document_observed"] is False
    assert result["decision_authority"] is False
