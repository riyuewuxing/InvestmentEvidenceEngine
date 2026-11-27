from copy import deepcopy

import pytest

from investment_evidence_engine.etf_report_diagnostics import (
    closing_premium,
    compare_reports,
    evaluate_report,
)


def fixture(symbol="510001"):
    # Synthetic, not an issuer's report or observed price.
    perf = {"nav_return_pct": "-10.00", "nav_std_pct": "1.10",
            "benchmark_return_pct": "-11.00", "benchmark_std_pct": "1.20",
            "return_difference_pp": "1.00", "std_difference_pp": "-0.10"}
    return {"symbol": symbol, "period_start": "2026-07-01", "period_end": "2026-09-30",
            "declared_report_day": "2026-10-27", "benchmark_label": "沪深300指数",
            "end_assets_cny": "1000.01", "end_nav_cny": "1.0000", "overview_end_units": "1000",
            "begin_units": "900", "created_units": "150", "redeemed_units": "50",
            "split_units_label": "DASH", "end_units": "1000",
            "realized_profit_cny": "10.00", "profit_cny": "-3.00",
            "performance": {h: dict(perf) for h in ("3M", "6M", "1Y")}}


def test_report_math_does_not_infer_cash_or_tracking_error():
    r = evaluate_report(fixture())
    assert r["nav_rounding_match"] and r["share_roll_forward_match"]
    assert r["net_creation_units"] == "100"
    assert r["net_creation_over_begin_pct"] == "11.111111"
    assert r["implied_fair_value_change_cny"] == "-13.00"
    assert r["split_label_was_dash"]
    for k in ("tracking_error_estimated", "cash_flow_cny_verified", "decision_authority", "formal_research_admitted"):
        assert r[k] is False


@pytest.mark.parametrize("key,value", [
    ("end_nav_cny", "1.0001"), ("overview_end_units", "999"), ("redeemed_units", "51"),
    ("split_units_label", "1"), ("end_assets_cny", 1000.01), ("created_units", True),
    ("declared_report_day", "2026-09-30"), ("period_start", "2026-07-02"),
    ("benchmark_label", "OTHER"), ("symbol", "600000"), ("begin_units", "0"),
    ("end_nav_cny", "1.0"), ("end_assets_cny", "1e3"),
])
def test_inconsistent_identity_date_basis_or_units_rejected(key, value):
    with pytest.raises(ValueError):
        evaluate_report(fixture() | {key: value})


@pytest.mark.parametrize("key,value", [("nav_std_pct", "-1.10"), ("nav_return_pct", "-101"),
                                       ("std_difference_pp", "0.10"), ("return_difference_pp", "1.02")])
def test_performance_reconciliation(key, value):
    f = fixture()
    f["performance"]["3M"][key] = value
    with pytest.raises(ValueError):
        evaluate_report(f)


def test_identical_benchmark_numbers_not_verified_index_version():
    a, b = fixture("510001"), fixture("510002")
    b["performance"]["3M"].update(nav_return_pct="-9.95", return_difference_pp="1.05")
    b["benchmark_label"] = "沪深300指数收益率"
    r = compare_reports(a, b)
    assert r["paired_reported_horizons"]["3M"]["left_minus_right_nav_return_pp"] == "-0.05"
    assert r["reported_benchmark_numbers_match"] and not r["benchmark_version_verified"]
    assert not r["expected_alpha_estimated"] and not r["inception_returns_compared"]
    wrong = deepcopy(b)
    wrong["performance"]["3M"].update(benchmark_return_pct="-10.99", return_difference_pp="1.04")
    with pytest.raises(ValueError, match="BENCHMARK_VALUES_CONFLICT"):
        compare_reports(a, wrong)


def test_closing_premium_uses_same_session_not_live_price():
    f = fixture()
    r = closing_premium(f, symbol=f["symbol"], session=f["period_end"], raw_close="1.010")
    assert r["close_over_reported_nav_minus_one_pct"] == "1.000000"
    assert float(r["nav_rounding_interval_pct"][0]) < 1 < float(r["nav_rounding_interval_pct"][1])
    assert not r["arbitrage_or_fill_inferred"]
    with pytest.raises(ValueError, match="PRICE_SCOPE"):
        closing_premium(f, symbol=f["symbol"], session="2026-10-27", raw_close="1.010")


def test_quarter_end_must_be_calendar_quarter_end():
    with pytest.raises(ValueError, match="QUARTER_SCOPE"):
        evaluate_report(fixture() | {"period_end": "2026-09-29"})


def test_nav_bounds_round_outward():
    from decimal import Decimal
    f = fixture()
    result = closing_premium(f, symbol=f["symbol"], session=f["period_end"], raw_close="1.010")
    lower, upper = map(Decimal, result["nav_rounding_interval_pct"])
    assert lower <= (Decimal("1.010") / Decimal("1.00005") - 1) * 100
    assert upper >= (Decimal("1.010") / Decimal("0.99995") - 1) * 100
