"""Synthetic producer-to-projection contract; no real holdings or vendor rows."""
import copy
import json
from datetime import UTC, datetime

import pytest

from investment_evidence_engine.market_coverage_projection import parse_market_coverage
from investment_evidence_engine.public_multiasset_coverage import recovery_lens

DAY = "2026-01-08"
OLD = "2026-01-07"
NOW = datetime(2026, 1, 8, 9, tzinfo=UTC)
SHA = "a" * 40


def record(marker, payload):
    data = {
        "status": "WARN", "executor_commit": SHA,
        "research_only": True, "decision_authority": False,
        "execution_allowed": False, **payload,
    }
    return {
        "repo": "riyuewuxing/InvestmentEvidenceEngine", "marker": marker,
        "conclusion": "success", "run_id": 1, "job_id": 2,
        "executor_commit": SHA,
        "log_line": "2026-01-08T08:00:00Z " + marker + " " + json.dumps(data),
    }


def scope(*, etf=False, observed=True):
    codes = {"fixture-a", "fixture-b", "fixture-c", "fixture-d", "fixture-e"}
    rows = {
        "fixture-a": {"day": OLD, "month": 1, "year": -2},
        "fixture-b": {"day": OLD, "month": -1, "year": -3},
        "fixture-c": {"day": OLD, "month": 2, "year": -1},
        "fixture-d": {"day": DAY if observed else OLD, "month": -1, "year": -2},
    }
    return {
        "code_count": len(codes), "official_universe_verified": False,
        "rank_coverage": {"denominator": len(codes), "numerator": len(rows)},
        "recovery_lens": recovery_lens(codes, {"records": rows}, observed_day=DAY),
        **({"subtype_unknown_count": len(codes), "subtype_verified_count": 0}
           if etf else {"share_class_not_product_count": True}),
    }


def archive(*, observed=True):
    return {
        "schema": "PUBLIC_DISCOVERY_OBSERVATION_ARCHIVE_V1",
        "research_only": True, "execution_allowed": False, "formal_admission": False,
        "observed_day": DAY,
        "records": {
            "stock": record("PUBLIC_UNIVERSE_CONTROL", {
                "as_of": DAY, "normalized_universe_rows_verified": 8,
                "independent_rank_derivation_verified": True,
                "operations": [
                    {"operation_id": "market-universe", "capture": {"row_count": 8}},
                    {"operation_id": "opportunity-scan", "scan": {
                        "screened_count": 6, "candidate_count": 2, "pit_safe": False,
                        "research_only": True,
                        "ranking_semantics": "RESEARCH_PRIORITY_NOT_RETURN_FORECAST",
                    }},
                ],
            }),
            "fund_etf": record("PUBLIC_MULTIASSET_COVERAGE", {
                "observed_day": DAY, "formal_pit": False,
                "fund_vendor_catalog_scope": scope(observed=observed),
                "etf_vendor_catalog_scope": scope(etf=True, observed=observed),
            }),
            "industry": record("PUBLIC_INDUSTRY_COVERAGE", {
                "observed_day": DAY, "formal_pit": False, "recent_scope_count": 3,
                "common_identity_complete_count": 2, "match_count": 1,
                "windows": {k: {"selected_day": v} for k, v in
                            {"year": "2025-01-08", "month": "2025-12-08", "recent": DAY}.items()},
                "expectation_gap_verified": False, "fundamental_recovery_verified": False,
                "research_candidates": [{"code": "801999", "industry": "synthetic",
                                         "long_price_return_pct": -2,
                                         "short_price_return_pct": 1, "matches": True}],
            }),
        },
    }


def parse(raw, now=NOW):
    return parse_market_coverage(json.dumps(raw).encode(), now=now)


def rewrite(raw, key, edit):
    item = raw["records"][key]
    prefix, payload = item["log_line"].rsplit(" " + item["marker"] + " ", 1)
    obj = json.loads(payload)
    edit(obj)
    item["log_line"] = prefix + " " + item["marker"] + " " + json.dumps(obj)


def test_actual_producer_shape_separates_dominant_date_and_observed_date():
    view = parse(archive())
    assert view.status == "OBSERVED_WARN"
    assert view.research_only and not view.formal_admission and not view.execution_allowed
    for row in view.rows[1:3]:
        assert (row.denominator, row.available, row.eligible, row.matches) == (5, 4, 3, 2)
        assert row.comparison_day == OLD
        assert (row.observed_day_dated_rows, row.observed_day_eligible,
                row.observed_day_matches) == (1, 1, 0)
    assert view.rows[0].observed_day_matches is None
    assert view.industries[0].industry == "synthetic"


def test_absent_observed_date_is_not_zero():
    view = parse(archive(observed=False))
    assert view.status == "OBSERVED_WARN"
    for row in view.rows[1:3]:
        assert row.comparison_day == OLD
        assert row.observed_day_dated_rows is None
        assert row.observed_day_eligible is None
        assert row.observed_day_matches is None


@pytest.mark.parametrize("kind", ["forged_today", "future_cohort", "dominant",
                                  "double_count", "invalid_hash", "mismatched_counts",
                                  "invalid_missing", "authority", "duplicate_operation"])
def test_rejects_contradictory_receipt(kind):
    data = archive()
    if kind == "authority":
        data["formal_admission"] = True
    elif kind == "duplicate_operation":
        rewrite(data, "stock", lambda p: p["operations"].append(copy.deepcopy(p["operations"][0])))
    else:
        def corrupt(p):
            r = p["fund_vendor_catalog_scope"]["recovery_lens"]
            if kind == "forged_today":
                r["observed_day_cohort"]["matches"] = 1
            elif kind == "future_cohort":
                r["date_cohorts"]["2026-01-09"] = copy.deepcopy(r["date_cohorts"][DAY])
                r["nav_day_counts"]["2026-01-09"] = 1
            elif kind == "dominant":
                r["dominant_eligible_day"] = DAY
            elif kind == "double_count":
                r["date_cohorts"][OLD]["dated_rows"] = 4
                r["nav_day_counts"][OLD] = 4
            elif kind == "invalid_hash":
                r["date_cohorts"][OLD]["top20_order_sha256"] = "bad"
            elif kind == "mismatched_counts":
                r["nav_day_counts"][OLD] = 1
            else:
                r["missing_or_other_day"] = 0
        rewrite(data, "fund_etf", corrupt)
    result = parse(data)
    assert not result.formal_admission
    if kind == "authority":
        assert result.status == "INVALID" and not result.rows
    else:
        assert result.status == "PARTIAL_WARN"
        asset = "A股" if kind == "duplicate_operation" else "场外基金"
        assert [(x.asset, x.status) for x in result.asset_issues] == [(asset, "INVALID")]
        assert len(result.rows) == 3 and asset not in {r.asset for r in result.rows}


def test_stale_and_future_are_distinct():
    assert parse(archive(), datetime(2026, 1, 9, 0, tzinfo=UTC)).status == "STALE"
    assert parse(archive(), datetime(2026, 1, 8, 7, tzinfo=UTC)).status == "INVALID"
    assert parse_market_coverage(b'{"schema":1,"schema":2}', now=NOW).status == "INVALID"


def test_missing_record_preserves_other_asset_observations():
    data = archive()
    del data["records"]["stock"]
    result = parse(data)
    assert result.status == "PARTIAL_WARN"
    assert [(x.asset, x.status) for x in result.asset_issues] == [("A股", "UNAVAILABLE")]
    assert [r.asset for r in result.rows] == ["场外基金", "ETF", "申万一级行业"]
    assert result.status != "OBSERVED_WARN"
    assert parse(data, datetime(2026, 1, 9, 0, tzinfo=UTC)).status == "STALE"


def test_missing_scope_does_not_erase_other_fund_scope():
    data = archive()
    rewrite(data, "fund_etf", lambda p: p.pop("etf_vendor_catalog_scope"))
    result = parse(data)
    assert result.status == "PARTIAL_WARN"
    assert [(x.asset, x.status) for x in result.asset_issues] == [("ETF", "UNAVAILABLE")]
    assert [r.asset for r in result.rows] == ["A股", "场外基金", "申万一级行业"]


@pytest.mark.parametrize("bad", ["failed", "clock", "authority"])
def test_failed_or_invalid_receipt_cannot_promote_its_assets(bad):
    data = archive()
    rec = data["records"]["fund_etf"]
    if bad == "failed":
        rec["conclusion"] = "failure"
    elif bad == "clock":
        rec["log_line"] = rec["log_line"].replace("T08:00:00Z", "T10:00:00Z", 1)
    else:
        rewrite(data, "fund_etf", lambda p: p.update(formal_pit=True))
    result = parse(data)
    assert result.status == "PARTIAL_WARN"
    assert [(x.asset, x.status) for x in result.asset_issues] == [
        ("场外基金", "INVALID"), ("ETF", "INVALID")]
    assert [r.asset for r in result.rows] == ["A股", "申万一级行业"]


def test_no_sources_is_unavailable_not_four_zero_counts():
    data = archive()
    data["records"] = {}
    result = parse(data)
    assert result.status == "UNAVAILABLE" and not result.rows
    assert len(result.asset_issues) == 4
    assert all(x.status == "UNAVAILABLE" for x in result.asset_issues)
    data["records"]["unexpected"] = None
    assert parse(data).status == "INVALID"
