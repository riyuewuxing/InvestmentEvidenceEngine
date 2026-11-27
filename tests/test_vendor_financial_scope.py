from datetime import date, datetime

import pytest

from investment_evidence_engine.vendor_financial_scope import (
    announcement_clock,
    consolidated_basis,
    financial_date_scope,
    select_same_notice,
    vendor_day,
)


@pytest.mark.parametrize("value", ["20260431", "2026-04-31", "2026-04-01T00:00:00", " 20260401",
                                  True, 20260401, datetime(2026, 4, 1)])
def test_date_only_no_silent_coercion(value):
    with pytest.raises(ValueError, match="VENDOR_DATE"):
        vendor_day(value)


def test_report_clocks_conservatively_use_later_label():
    result = financial_date_scope("20251231", "20260331", "20260401")
    assert result["declared_date_ceiling"] == "2026-04-01"
    assert result["notice_fields_disagree"] and not result["historical_vintage_verified"]
    assert not result["first_availability_verified"]
    assert financial_date_scope(date(2025, 12, 31), "20260331", None)["declared_date_ceiling"] == "2026-03-31"


@pytest.mark.parametrize("ann,actual", [("20251230", "20260331"), ("20260331", "bad"), (None, None)])
def test_bad_report_clock_cannot_be_repaired_by_earlier_or_other_clock(ann, actual):
    with pytest.raises(ValueError, match="VENDOR_"):
        financial_date_scope("20251231", ann, actual)


@pytest.mark.parametrize("value", [str(i) for i in range(2, 13)] + [True, 1.0, None, "01"])
def test_latest_consolidated_not_other_basis(value):
    with pytest.raises(ValueError, match="VENDOR_REPORT_BASIS"):
        consolidated_basis(value)


def test_latest_consolidated_never_original_vintage():
    assert consolidated_basis("1") == consolidated_basis(1) == "LATEST_CONSOLIDATED_VENDOR_ROW"
    assert consolidated_basis(None, allow_unspecified=True) == "UNSPECIFIED_DIAGNOSTIC_ONLY"


def test_conflicting_same_notice_not_resolved_by_update_flag():
    a = {"dataset": "income", "report_period": "2025-12-31", "available_date": "2026-03-31",
         "report_basis": "LATEST_CONSOLIDATED_VENDOR_ROW", "revenue": 100, "update_flag": "0"}
    b = {**a, "revenue": 110, "update_flag": "1"}
    assert select_same_notice([a, b], metric_fields=("revenue",)) is None
    assert select_same_notice([b, a], metric_fields=("revenue",)) is None
    assert select_same_notice([a, dict(a)], metric_fields=("revenue",)) == a
    assert select_same_notice([a, {**a, "revenue": True}], metric_fields=("revenue",)) is None
    assert select_same_notice([a, {**a, "report_basis": "OTHER"}], metric_fields=("revenue",)) is None
    assert select_same_notice([{**a, "ts_code": "600000.SH"}, {**a, "ts_code": "600001.SH"}],
                              metric_fields=("revenue",)) is None


@pytest.mark.parametrize("rec,day,precision,basis", [
    ("2026-04-08", "2026-04-08", "DATE_ONLY", "DATE_ONLY"),
    ("2026-04-08T00:00:00", "2026-04-08", "DATE_ONLY", "MIDNIGHT_DATE_LABEL"),
    ("2026-04-08 14:00:00", "2026-04-08", "DATETIME", "VENDOR_LOCAL_CLOCK_ASSUMED"),
    ("2026-04-08T06:00:00Z", "2026-04-08", "DATETIME", "VENDOR_AWARE_CLOCK"),
    ("2026-04-08T17:00:00Z", "2026-04-09", "DATE_ONLY", "CONFLICTING_DAY_LABELS"),
    ("2026-04-07 14:00:00", "2026-04-08", "DATE_ONLY", "CONFLICTING_DAY_LABELS"),
])
def test_event_clock_projection_never_proves_availability(rec, day, precision, basis):
    result = announcement_clock("20260408", rec)
    assert (result["local_day"], result["precision"], result["clock_basis"]) == (day, precision, basis)
    assert not result["first_availability_verified"]
    assert not result["historical_vintage_verified"]
