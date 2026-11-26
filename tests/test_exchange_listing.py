import io
import json
from datetime import date

import openpyxl
import pytest

from investment_evidence_engine.exchange_listing import (
    _date_shape_summary,
    _listing_day,
    endpoint,
    parse_listing,
)

DAY = date(2026, 11, 26)


def sse(rows, total=None):
    return json.dumps({"result": rows, "pageHelp": {"total": len(rows) if total is None else total}}).encode()


def test_explicit_sse_board_total_and_future():
    rows = [{"A_STOCK_CODE": f"688{i:03d}", "LIST_DATE": "2025-01-02"} for i in range(201)]
    rows[-1]["LIST_DATE"] = "2026-11-27"
    codes, meta = parse_listing(sse(rows), "sse_star", DAY)
    assert len(codes) == 200 and meta["future_listing_dates_excluded"] == 1
    assert meta["declared_total_match"] and not meta["complete_listing_verified"]
    assert "query.sse.com.cn" in endpoint("sse_star")[0]


@pytest.mark.parametrize("mode", ["duplicate", "wrong_board", "wrong_total", "bad_date"])
def test_invalid_sse_observation(mode):
    rows = [{"A_STOCK_CODE": f"688{i:03d}", "LIST_DATE": "2025-01-02"} for i in range(201)]
    if mode == "duplicate":
        rows.append(rows[-1])
    elif mode == "wrong_board":
        rows[0]["A_STOCK_CODE"] = "600519"
    elif mode == "bad_date":
        rows[0]["LIST_DATE"] = "2025-01"
    with pytest.raises(ValueError):
        parse_listing(sse(rows, total=200 if mode == "wrong_total" else None), "sse_star", DAY)


def test_szse_numeric_cells_have_explicit_exchange_identity():
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["A股代码", "A股上市日期"])
    for i in range(1000):
        sheet.append([i, date(2020, 1, 1)])
    buffer = io.BytesIO()
    book.save(buffer)
    book.close()
    codes, meta = parse_listing(buffer.getvalue(), "szse_a", DAY)
    assert len(codes) == 1000 and codes[1] == "sz.000001"
    assert not meta["declared_total_match"]


@pytest.mark.parametrize("value", ["20260102", "2026-01-02", "2026-01-02 00:00:00",
                                  "2026-01-02T00:00:00.000"])
def test_only_explicit_calendar_date_formats(value):
    assert _listing_day(value) == date(2026, 1, 2)


@pytest.mark.parametrize("value", ["202601", "2026-01-02 12:30:00", "", None, 20260102])
def test_no_guessing_missing_or_ambiguous_listing_date(value):
    with pytest.raises(ValueError):
        _listing_day(value)


def test_schema_diagnostic_does_not_echo_listing_values():
    body = sse([{"LIST_DATE": "20260102"}, {"LIST_DATE": "2026-01-03"},
                {"LIST_DATE": "2026-01-03 00:00:00"}, {"LIST_DATE": None}, {"LIST_DATE": "unknown"}])
    result = _date_shape_summary(body, "sse_main")
    assert set(result["listing_date_shapes"].values()) == {1}
    assert "unknown" not in json.dumps(result)
