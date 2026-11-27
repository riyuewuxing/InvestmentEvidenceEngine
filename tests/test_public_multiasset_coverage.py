from investment_evidence_engine.public_multiasset_coverage import (
    analyze,
    normalize,
    number,
    overlap,
    recovery_lens,
    summary,
)


def table(key, fields, rows):
    return normalize(key, fields, rows)


def test_duplicate_identity_excludes_all_and_does_not_guess_missing():
    cols = ["基金代码", "基金简称", "基金类型"]
    rows = [{"基金代码": "000001", "基金简称": "first"}, {"基金代码": "000001", "基金简称": "second"},
            {"基金代码": "000002", "基金简称": "third"}, {"基金代码": "2"}]
    t = table("fund_catalog", cols, rows)
    assert t["records"] == {"000002": {"name": "third", "category": None}}
    assert summary(t)["ambiguous_duplicate_rows"] == 2
    assert summary(t)["invalid_rows"] == 1
    assert number("-") is None and number(float("inf")) is None and number(False) is None
    assert number("0%") == 0


def test_coverage_uses_catalog_denominator_and_missing_is_not_zero():
    assert overlap({"a", "b"}, {"b", "c"}) == {"denominator": 2, "numerator": 1, "coverage": 0.5, "extra": 1}
    assert overlap({"a"}, set())["coverage"] == 0
    assert overlap({"a"}, None)["coverage"] is None
    assert overlap(set(), {"a"})["coverage"] is None


def test_recovery_only_actual_dated_complete_values_and_strict_signs():
    rows = {"000001": {"day": "2026-11-26", "month": 1, "year": -10},
            "000002": {"day": "2026-11-26", "month": 0, "year": -20},
            "000003": {"day": "2026-11-25", "month": 2, "year": -30},
            "000004": {"day": "2026-11-26", "month": None, "year": -30},
            "000005": {"day": "2026-11-28", "month": 5, "year": -30}}
    report = recovery_lens(set(rows) | {"000006"}, {"records": rows}, observed_day="2026-11-27")
    assert report["denominator"] == 6
    assert report["eligible"] == 2 and report["matches"] == 1
    assert report["missing_or_other_day"] == 4
    assert report["latest_vendor_nav_day"] == "2026-11-26"
    assert not report["formal_pit"]


def test_feeder_not_etf_and_no_subtype_or_coverage_fabrication():
    master = table("fund_catalog", ["基金代码", "基金简称", "基金类型"], [
        {"基金代码": "000001", "基金简称": "ETF联接", "基金类型": "指数型"},
        {"基金代码": "510001", "基金简称": "ETF", "基金类型": "指数型"},
        {"基金代码": "000002", "基金简称": "普通基金"}])
    etfs = table("etf_catalog", ["基金代码", "基金名称", "基金类型", "最新-单位净值", "最新-交易日"], [
        {"基金代码": "510001", "基金名称": "ETF", "基金类型": "指数型", "最新-单位净值": "1.2"},
        {"基金代码": "000001", "基金名称": "ETF联接"}])
    report = analyze({"fund_catalog": master, "etf_catalog": etfs}, observed_day="2026-11-27")
    assert report["fund_vendor_catalog_scope"]["code_count"] == 2
    assert report["etf_vendor_catalog_scope"]["code_count"] == 1
    assert report["etf_vendor_catalog_scope"]["subtype_unknown_count"] == 1
    assert report["etf_vendor_catalog_scope"]["subtype_verified_count"] == 0
    assert report["etf_vendor_catalog_scope"]["secondary_quote_coverage"]["coverage"] is None
    assert report["industry_reversal"] == "UNKNOWN"
    assert not report["decision_authority"]


def test_sina_primary_scope_ths_extra_excluded_from_fund_and_missing_ths_visible():
    master = table("fund_catalog", ["基金代码", "基金简称", "基金类型"], [
        {"基金代码": "510001", "基金简称": "listed one"},
        {"基金代码": "510002", "基金简称": "listed two"},
        {"基金代码": "000003", "基金简称": "ordinary fund"}])
    quote = table("etf_quote", ["代码", "名称", "最新价", "成交额"], [
        {"代码": "sh510001", "名称": "listed one", "最新价": 1.2}])
    ths = table("etf_catalog", ["基金代码", "基金名称", "基金类型", "最新-单位净值", "最新-交易日"], [
        {"基金代码": "510002", "基金名称": "listed two", "最新-单位净值": 1.1, "最新-交易日": "2026-11-27"}])
    report = analyze({"fund_catalog": master, "etf_quote": quote, "etf_catalog": ths}, observed_day="2026-11-27")
    e = report["etf_vendor_catalog_scope"]
    assert e["denominator_source"] == "SINA_ETF_CATEGORY"
    assert e["independent_vendor_directory_overlap"]["coverage"] == 0
    assert e["independent_vendor_directory_overlap"]["extra"] == 1
    assert report["fund_vendor_catalog_scope"]["code_count"] == 1
    report = analyze({"fund_catalog": master, "etf_quote": quote}, observed_day="2026-11-27")
    assert report["etf_vendor_catalog_scope"]["independent_vendor_directory_overlap"]["coverage"] is None


def test_sparse_latest_day_cannot_suppress_prior_dominant_dated_cohort():
    rows = {
        "000001": {"day": "2026-11-26", "month": 1, "year": -10},
        "000002": {"day": "2026-11-26", "month": 2, "year": -20},
        "000003": {"day": "2026-11-27", "month": 1, "year": 10},
        "000004": {"day": "2026-11-27", "month": None, "year": -10},
    }
    r = recovery_lens(set(rows), {"records": rows}, observed_day="2026-11-27")
    assert r["dominant_eligible_day"] == "2026-11-26"
    assert r["latest_vendor_nav_day"] == "2026-11-27"
    assert r["eligible"] == 2 and r["matches"] == 2
    assert r["observed_day_cohort"]["eligible"] == 1
    assert r["observed_day_cohort"]["matches"] == 0
    assert r["date_cohorts"]["2026-11-27"]["dated_rows"] == 2
