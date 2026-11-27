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
