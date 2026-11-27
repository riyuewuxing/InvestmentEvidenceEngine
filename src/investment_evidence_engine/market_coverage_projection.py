"""Read-only projection of public runner diagnostics. Not a current PIT receipt or advice."""
from __future__ import annotations

import json
import math
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

REPO = "riyuewuxing/InvestmentEvidenceEngine"
MAX_BYTES = 256 * 1024


class CoverageRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset: str
    denominator: int
    available: int | None = None
    eligible: int | None = None
    matches: int | None = None
    comparison_day: str | None = None
    observed_day_dated_rows: int | None = None
    observed_day_eligible: int | None = None
    observed_day_matches: int | None = None
    scope_note: str
    source_run: int


class IndustryCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    industry: str
    long_price_return_pct: float
    short_price_return_pct: float


class CoverageIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset: str
    status: Literal["UNAVAILABLE", "INVALID"]


class MarketCoverageView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["UNAVAILABLE", "INVALID", "OBSERVED_WARN", "PARTIAL_WARN", "STALE"]
    observed_day: str | None = None
    oldest_log_at: str | None = None
    latest_log_at: str | None = None
    rows: tuple[CoverageRow, ...] = ()
    asset_issues: tuple[CoverageIssue, ...] = ()
    industries: tuple[IndustryCandidate, ...] = ()
    industry_dates: tuple[str, ...] = ()
    source_ref: str | None = None
    reason: str
    research_only: Literal[True] = True
    execution_allowed: Literal[False] = False
    formal_admission: Literal[False] = False


def _unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("DUPLICATE_KEY")
        out[key] = value
    return out


def _constant(value):
    raise ValueError("NONFINITE_JSON")


def _read_json(raw: str):
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=_constant)


def _count(value: Any, limit: int = 100000) -> int:
    if type(value) is not int or not 0 <= value <= limit:
        raise ValueError("INVALID_COUNT")
    return value


def _day(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("INVALID_DAY")
    return date.fromisoformat(value).isoformat()


def _time(value: str) -> datetime:
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.utcoffset() is None:
        raise ValueError("NAIVE_CLOCK")
    return t.astimezone(UTC)


def _receipt(record: dict, marker: str) -> tuple[dict, datetime, int]:
    if record["repo"] != REPO or record["marker"] != marker or record["conclusion"] != "success":
        raise ValueError("RECEIPT_SCOPE")
    run = _count(record["run_id"], 10**14)
    job = _count(record["job_id"], 10**14)
    if not run or not job:
        raise ValueError("RECEIPT_ID")
    line = record["log_line"]
    stamp, sep, payload = line.partition(" " + marker + " ")
    if not sep:
        raise ValueError("RECEIPT_MARKER")
    parsed = _read_json(payload)
    if (not isinstance(parsed, dict) or parsed.get("status") != "WARN"
            or parsed.get("executor_commit") != record["executor_commit"]
            or not re.fullmatch(r"[0-9a-f]{40}", record["executor_commit"])
            or parsed.get("decision_authority") is not False
            or parsed.get("execution_allowed") is not False):
        raise ValueError("RECEIPT_AUTHORITY")
    return parsed, _time(stamp), run


def _fund_row(scope: dict, run: int, day: str, *, etf: bool) -> CoverageRow:
    n = _count(scope["code_count"])
    rank = scope["rank_coverage"]
    rec = scope["recovery_lens"]
    if (rank["denominator"] != n or rec["denominator"] != n
            or scope["official_universe_verified"] is not False
            or rec["formal_pit"] is not False
            or rec["expected_return_verified"] is not False):
        raise ValueError("SCOPE_OR_AUTHORITY")
    available = _count(rank["numerator"], n)
    eligible = _count(rec["eligible"], available)
    matches = _count(rec["matches"], eligible)
    cohort_day = _day(rec["dominant_eligible_day"])
    cohorts = rec["date_cohorts"]
    nav_counts = rec["nav_day_counts"]
    if (rec["status"] != "OBSERVED_VENDOR_NAV_RETURN_DIAGNOSTIC"
            or rec["observed_day"] != day or not isinstance(cohorts, dict)
            or not cohorts or not isinstance(nav_counts, dict)
            or set(cohorts) != set(nav_counts)):
        raise ValueError("COHORT_SCOPE")
    total_dated = 0
    for stamp, cohort in cohorts.items():
        if _day(stamp) > day:
            raise ValueError("FUTURE_COHORT")
        dated = _count(cohort["dated_rows"], available)
        complete = _count(cohort["eligible"], dated)
        matched = _count(cohort["matches"], complete)
        if (dated == 0 or _count(nav_counts[stamp], available) != dated
                or _count(cohort["top20_count"], 20) != min(20, matched)
                or not isinstance(cohort["top20_order_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", cohort["top20_order_sha256"])):
            raise ValueError("COHORT_COUNTS")
        total_dated += dated
    if total_dated > available:
        raise ValueError("COHORT_DOUBLE_COUNT")
    dominant = max(cohorts, key=lambda stamp: (cohorts[stamp]["eligible"], stamp))
    selected = cohorts[dominant]
    if (cohort_day != dominant or rec["latest_vendor_nav_day"] != max(cohorts)
            or selected["eligible"] != eligible or selected["matches"] != matches
            or rec["top20_order_sha256"] != selected["top20_order_sha256"]
            or _count(rec["missing_or_other_day"], n) != n - eligible
            or rec["observed_day_cohort"] != cohorts.get(day)):
        raise ValueError("COHORT_MISMATCH")
    today = cohorts.get(day)
    if etf:
        unknown = _count(scope["subtype_unknown_count"], n)
        verified = _count(scope["subtype_verified_count"], n)
        # This vendor-only receipt carries no authenticated product identities.
        # A positive verified count needs a separate evidence schema and cannot
        # be accepted from a bare aggregate or a name-derived category.
        if verified != 0 or unknown != n:
            raise ValueError("SUBTYPE_SCOPE")
        note = f"供应商场内ETF目录；{unknown} 个子类型待核验，非交易所完整清单"
        asset = "ETF"
    else:
        if scope["share_class_not_product_count"] is not True:
            raise ValueError("SHARE_CLASS_SCOPE")
        note = "供应商份额级目录，非独立产品数量；未核验正式基金类型"
        asset = "场外基金"
    return CoverageRow(
        asset=asset, denominator=n, available=available, eligible=eligible,
        matches=matches, comparison_day=cohort_day, scope_note=note, source_run=run,
        observed_day_dated_rows=today["dated_rows"] if today is not None else None,
        observed_day_eligible=today["eligible"] if today is not None else None,
        observed_day_matches=today["matches"] if today is not None else None,
    )


_INVALID = (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError, IndexError)


def _stock_row(stock: dict, sr: int) -> CoverageRow:
    operations = stock["operations"]
    ops = {x["operation_id"]: x for x in operations}
    if len(operations) != 2 or set(ops) != {"market-universe", "opportunity-scan"}:
        raise ValueError("STOCK_OPERATION_SCOPE")
    universe = _count(ops["market-universe"]["capture"]["row_count"])
    scan = ops["opportunity-scan"]["scan"]
    scanned = _count(scan["screened_count"], universe)
    candidates = _count(scan["candidate_count"], scanned)
    if (stock["normalized_universe_rows_verified"] != universe
            or stock["independent_rank_derivation_verified"] is not True
            or scan["ranking_semantics"] != "RESEARCH_PRIORITY_NOT_RETURN_FORECAST"
            or scan["research_only"] is not True or scan["pit_safe"] is not False):
        raise ValueError("STOCK_RANK_SCOPE")
    return CoverageRow(asset="A股", denominator=universe, available=scanned, eligible=None,
                        matches=candidates, comparison_day=None, source_run=sr,
                        scope_note="供应商有效记录；上市清单/行情交易日未核验；日跌幅与成交额研究筛选")


def _industry_rows(sector: dict, ir: int, day: str) -> tuple:
    n = _count(sector["recent_scope_count"], 500)
    eligible = _count(sector["common_identity_complete_count"], n)
    matches = _count(sector["match_count"], eligible)
    dates = tuple(_day(sector["windows"][k]["selected_day"]) for k in ("year", "month", "recent"))
    if not dates[0] < dates[1] < dates[2] <= day:
        raise ValueError("INDUSTRY_DATES")
    if sector["expectation_gap_verified"] is not False or sector["fundamental_recovery_verified"] is not False:
        raise ValueError("INDUSTRY_AUTHORITY")
    inds = []
    seen = set()
    for x in sector["research_candidates"]:
        code, name = x["code"], x["industry"]
        long, short = x["long_price_return_pct"], x["short_price_return_pct"]
        if (not isinstance(code, str) or not re.fullmatch(r"801[0-9]{3}", code) or code in seen
                or not isinstance(name, str) or not 0 < len(name) <= 80
                or type(long) not in (int, float) or type(short) not in (int, float)
                or not math.isfinite(long) or not math.isfinite(short) or not long < 0 < short
                or x["matches"] is not True):
            raise ValueError("INDUSTRY_CANDIDATE")
        seen.add(code)
        inds.append(IndustryCandidate(code=code, industry=name, long_price_return_pct=long, short_price_return_pct=short))
    if len(inds) != min(matches, 10):
        raise ValueError("INDUSTRY_MATCH_COUNT")
    row = CoverageRow(asset="申万一级行业", denominator=n, available=eligible,
                      eligible=eligible, matches=matches, comparison_day=dates[2],
                      source_run=ir, scope_note="同身份三期价格指数；非总回报、基本面反转或预期差")
    return row, tuple(inds), dates


def parse_market_coverage(raw: bytes, *, source_ref: str | None = None,
                          now: datetime | None = None) -> MarketCoverageView:
    """Check the common envelope, then independently validate each asset.

    A bad source cannot turn into a zero count or erase an independent valid
    observation. The archive and each receipt remain strictly research-only.
    Failed runner receipts are never promoted to successful observations.
    """
    try:
        if len(raw) > MAX_BYTES:
            raise ValueError("ARCHIVE_SIZE")
        a = _read_json(raw.decode("utf-8"))
        if (a["schema"] != "PUBLIC_DISCOVERY_OBSERVATION_ARCHIVE_V1"
                or a["research_only"] is not True or a["execution_allowed"] is not False
                or a["formal_admission"] is not False):
            raise ValueError("ARCHIVE_AUTHORITY")
        day = _day(a["observed_day"])
        records = a["records"]
        if not isinstance(records, dict) or set(records) - {"stock", "fund_etf", "industry"}:
            raise ValueError("ARCHIVE_SCOPE")
        clock = now or datetime.now(UTC)
        if clock.utcoffset() is None:
            raise ValueError("NAIVE_NOW")
        local_day = clock.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
        if day > local_day:
            raise ValueError("ARCHIVE_CLOCK")
    except _INVALID:
        return MarketCoverageView(status="INVALID", source_ref=source_ref,
                                  reason="观察回执公共结构、日期或权限校验失败。")

    rows = []
    issues = []
    timestamps = []
    inds, dates = (), ()

    def issue(asset, status):
        issues.append(CoverageIssue(asset=asset, status=status))

    def checked(key, marker, day_field, assets):
        if records.get(key) is None:
            for asset in assets:
                issue(asset, "UNAVAILABLE")
            return None
        try:
            payload, stamp, run = _receipt(records[key], marker)
            if (stamp > clock or stamp.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat() != day
                    or payload[day_field] != day
                    or (key != "stock" and (payload.get("formal_pit") is not False
                                            or payload.get("research_only") is not True))):
                raise ValueError("RECEIPT_CLOCK_OR_AUTHORITY")
            return payload, stamp, run
        except _INVALID:
            for asset in assets:
                issue(asset, "INVALID")
            return None

    stock = checked("stock", "PUBLIC_UNIVERSE_CONTROL", "as_of", ("A股",))
    if stock is not None:
        payload, stamp, run = stock
        try:
            rows.append(_stock_row(payload, run))
            timestamps.append(stamp)
        except _INVALID:
            issue("A股", "INVALID")

    fund = checked("fund_etf", "PUBLIC_MULTIASSET_COVERAGE", "observed_day", ("场外基金", "ETF"))
    if fund is not None:
        payload, stamp, run = fund
        for key, asset, etf in (("fund_vendor_catalog_scope", "场外基金", False),
                                ("etf_vendor_catalog_scope", "ETF", True)):
            if payload.get(key) is None:
                issue(asset, "UNAVAILABLE")
                continue
            try:
                rows.append(_fund_row(payload[key], run, day, etf=etf))
                timestamps.append(stamp)
            except _INVALID:
                issue(asset, "INVALID")

    sector = checked("industry", "PUBLIC_INDUSTRY_COVERAGE", "observed_day", ("申万一级行业",))
    if sector is not None:
        payload, stamp, run = sector
        try:
            row, inds, dates = _industry_rows(payload, run, day)
            rows.append(row)
            timestamps.append(stamp)
        except _INVALID:
            issue("申万一级行业", "INVALID")

    if not rows:
        invalid = any(x.status == "INVALID" for x in issues)
        return MarketCoverageView(status="INVALID" if invalid else "UNAVAILABLE",
                                  source_ref=source_ref, asset_issues=tuple(issues),
                                  reason="没有可核验资产观察；缺失及无效资产不能按零机会解释。")
    stale = clock - min(timestamps) > timedelta(hours=24) or local_day != day
    return MarketCoverageView(
        status="STALE" if stale else "PARTIAL_WARN" if issues else "OBSERVED_WARN",
        observed_day=day, oldest_log_at=min(timestamps).isoformat(),
        latest_log_at=max(timestamps).isoformat(), rows=tuple(rows), asset_issues=tuple(issues),
        industries=inds, industry_dates=dates, source_ref=source_ref,
        reason=("历史观察已过期，仅供回顾。" if stale else "最近一次公开供应商观察，非实时行情承诺。")
               + ("部分资产回执缺失或无效，仅保留其余已核验观察。" if issues else "")
               + "基金/ETF最大完整日期组与观察日组分别展示，观察日缺行不等于零机会。"
               + "未公开实际证券短名单；未独立核验正式PIT、费率、申赎、类型及交易可行性。",
    )
