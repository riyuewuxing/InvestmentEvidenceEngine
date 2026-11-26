import pytest

from investment_evidence_engine.alfred_vintage_control import (
    VINTAGES,
    compare_vintages,
    parse_vintage,
    vintage_url,
)


def csv_body(vintage, august="159022", july="159000"):
    return (f"observation_date,PAYEMS_{vintage:%Y%m%d}\n"
            f"2025-07-01,{july}\n2025-08-01,{august}\n").encode()


def test_missing_before_release_is_not_zero():
    assert parse_vintage(csv_body(VINTAGES[0], ""), VINTAGES[0])["august_change_jobs"] is None
    assert parse_vintage(csv_body(VINTAGES[1]), VINTAGES[1])["august_change_jobs"] == 22000
    assert "vintage_date=2025-09-05" in vintage_url(VINTAGES[1])


@pytest.mark.parametrize("body, error", [
    (b"observation_date,PAYEMS\n2025-07-01,159000\n", "VINTAGE_HEADER"),
    (b"observation_date,PAYEMS_20250904\n2025-07-01,159000\n", "VINTAGE_HEADER"),
    (b"observation_date,PAYEMS_20250905\n2025-07-01,159000\n2025-07-01,159000\n", "MONTHLY_ORDER"),
    (b"observation_date,PAYEMS_20250905\n2025-07-01,159000\n2025-08-01,NaN\n", "LEVEL_SCHEMA"),
    (b"observation_date,PAYEMS_20250905\n2025-07-01,159000\n2025-08-01,159022\n2025-10-01,159020\n",
     "FUTURE_MEASUREMENT"),
    (b"observation_date,PAYEMS_20250905\n2025-07-01,159000\n2025-08-01,.\n", "AUGUST_MISSING"),
])
def test_rejects_schema_or_future_leakage(body, error):
    with pytest.raises(ValueError, match=error):
        parse_vintage(body, VINTAGES[1])


def test_same_date_archive_crosscheck_is_not_pit_promotion():
    receipts = [
        {"requested_vintage": d.isoformat(), "status": "OBSERVED",
         "fields": parse_vintage(csv_body(d, value), d)}
        for d, value in zip(VINTAGES, ["", "159022", "158996", "158974"], strict=True)
    ]
    result = compare_vintages(receipts, (22000, -4000, -26000))
    assert result["comparison"] == "MATCH"
    assert result["status"] == "WARN"
    assert not result["pit_safe"]
    assert not result["historical_system_capture_verified"]
    assert compare_vintages(receipts, (22000, -4000, -25000))["comparison"] == "CONFLICT"
    receipts[0]["status"] = "BLOCK"
    assert compare_vintages(receipts, (22000, -4000, -26000))["comparison"] == "INCOMPLETE"
