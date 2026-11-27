from datetime import UTC, datetime

import pytest

from investment_evidence_engine.cross_exchange_release_control import (
    EXPECTED,
    URLS,
    parse_index,
    reconcile,
    row_pair,
)


def index_html(stamp="28/08/2024 17:55"):
    return f'<table><tr><td>{stamp}</td><td>01211 81211 BYD COMPANY</td><td><a href="{URLS["hk"]}">2024 INTERIM RESULTS ANNOUNCEMENT</a></td></tr></table>'


def test_release_row_exact_link_and_minute_precision():
    result = parse_index(index_html())
    assert result["publisher_release_minute_start"] == "2024-08-28T17:55:00+08:00"
    assert result["conservative_minute_end_exclusive"] == "2024-08-28T17:56:00+08:00"
    with pytest.raises(ValueError):
        parse_index(index_html("28/08/2024 14:55"))
    with pytest.raises(ValueError):
        parse_index(index_html().replace(URLS["hk"], "https://example.com/test.pdf"))
    with pytest.raises(ValueError):
        parse_index(index_html() + index_html())


def test_units_and_anchored_values():
    assert row_pair("營業收入 4 301,126,713 260,124,143", "營業收入", scale=1000, note=True) == EXPECTED["revenue"]
    assert row_pair("营业收入（元） 301,126,713,000.00 260,124,143,000.00", "营业收入(元)", scale=1) == EXPECTED["revenue"]
    with pytest.raises(ValueError):
        row_pair("营业收入（元） 301,126,713 260,124,143", "营业收入(元)", scale=1)


def test_two_channel_match_is_not_historical_observation():
    data = {"values_cny": EXPECTED, "report_period_end": "2024-06-30"}
    result = reconcile(parse_index(index_html()), data, data, observed_at=datetime(2026, 11, 27, tzinfo=UTC))
    assert result["status"] == "WARN"
    assert not result["pit_safe"]
    assert [v["declared_release_minute_elapsed"] for v in result["cutoffs"]] == [False, False, False, True, True]
    assert not any(v["actually_observed_by_cutoff"] for v in result["cutoffs"])
    assert reconcile(parse_index(index_html()), data, data | {"values_cny": {}}, observed_at=datetime(2026, 11, 27, tzinfo=UTC))["status"] == "BLOCK"
