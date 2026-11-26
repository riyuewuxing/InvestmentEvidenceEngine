"""One explicit retained TWSE revenue profile, using observed bytes, not historical PIT.

The provider classification is from the retained snapshot, not a historical
industry membership guarantee. This profile is not mainland price context.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from statistics import median

from .contracts import ExecutionOperation, OperationResult
from .evidence_time_guard import aware, validate_event_cutoff
from .transport_integrity import read_verified_artifact
from .twse_revenue_control import AMOUNTS, PERCENTS, REQUIRED, pct, percent, round_to
from .workers import WorkerContext, _artifact, _write_json

PROFILE = "TWSE_RETAINED_REVENUE_202610"
DIGEST = "0e6a2cbfb78befd2c77415e57aadfdf7acc1038a48e9d815bedb113730b622f2"
SIZE = 207911
OBSERVED = datetime.fromisoformat("2026-11-26T14:02:28.910547+00:00")
# First actual offline re-open test passed at 14:04:45.2817217 UTC.
# Round UP, never backdate availability to the snapshot's declared day.
VERIFIED = datetime.fromisoformat("2026-11-26T14:04:46+00:00")
ROOT = Path(__file__).resolve().parents[2]
RELATIVE = f"public-evidence/sha256/{DIGEST}.csv"
TARGET = "2330"
SECTOR = "半導體業"
PERIOD = "11510"
SNAPSHOT = "1151117"
EXPECTED_PARAMS = {"industry_profile", "archive_sha256", "market", "subject_ids", "as_of"}
PAIRS = {
    "mom": (AMOUNTS[0], AMOUNTS[1], PERCENTS[0]),
    "yoy": (AMOUNTS[0], AMOUNTS[2], PERCENTS[1]),
    "ytd_yoy": (AMOUNTS[3], AMOUNTS[4], PERCENTS[2]),
}


def read_rows(raw: bytes) -> list[dict[str, str]]:
    """Reject ambiguous identities and mixed report periods, don't read notes as signals."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 2 * 1024 * 1024:
        raise ValueError("TWSE_BREADTH_BODY_SCOPE")
    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig", errors="strict")), strict=True)
    header = next(reader, [])
    if set(header) != REQUIRED or len(header) != len(REQUIRED):
        raise ValueError("TWSE_BREADTH_HEADER_SCOPE")
    rows = []
    seen = set()
    for cells in reader:
        if len(rows) >= 5000 or len(cells) != len(header):
            raise ValueError("TWSE_BREADTH_ROW_SCOPE")
        row = dict(zip(header, cells, strict=True))
        code = row["公司代號"]
        if (not re.fullmatch(r"[0-9]{4,6}", code) or code in seen
                or not row["公司名稱"].strip() or not row["產業別"].strip()):
            raise ValueError("TWSE_BREADTH_IDENTITY_SCOPE")
        if row["資料年月"] != PERIOD or row["出表日期"] != SNAPSHOT:
            raise ValueError("TWSE_BREADTH_MIXED_PERIOD_OR_SNAPSHOT")
        seen.add(code)
        rows.append(row)
    if not rows:
        raise ValueError("TWSE_BREADTH_EMPTY")
    return rows


def _integer(value: str) -> int | None:
    # Do not convert a blank, dash, malformed or overlong value into zero.
    if not re.fullmatch(r"-?[0-9]{1,15}", value):
        return None
    return int(value)


def _pct_text(value: Decimal | None) -> str | None:
    return None if value is None else str(round_to(value, "0.000001"))


def pair_summary(rows: list[dict[str, str]], pair: tuple[str, str, str]) -> dict:
    current_key, base_key, rate_key = pair
    excluded: Counter[str] = Counter()
    rate_checks: Counter[str] = Counter()
    rates = []
    current_total = base_total = 0
    target_current = target_base = None
    for row in rows:
        current, base = _integer(row[current_key]), _integer(row[base_key])
        if current is None or base is None:
            excluded["MISSING_OR_INVALID_AMOUNT"] += 1
            continue
        if current < 0 or base < 0:
            excluded["NEGATIVE_AMOUNT"] += 1
            continue
        if base == 0:
            excluded["ZERO_COMPARISON_BASE"] += 1
            continue
        rate = pct(current, base)
        rates.append(rate)
        current_total += current
        base_total += base
        if row["公司代號"] == TARGET:
            target_current, target_base = current, base
        try:
            declared = percent(row[rate_key])
            rate_checks["MATCH" if abs(declared - rate) <= Decimal("0.011") else "CONFLICT"] += 1
        except ValueError:
            rate_checks["MISSING_OR_UNPARSEABLE"] += 1
    n = len(rates)
    if n + sum(excluded.values()) != len(rows) or sum(rate_checks.values()) != n:
        raise ValueError("TWSE_BREADTH_COUNT_RECONCILIATION")
    delta = current_total - base_total
    return {
        "observed_rows": len(rows), "amount_paired_rows": n,
        "excluded_rows": len(rows) - n, "exclusion_reasons": dict(sorted(excluded.items())),
        "provider_rate_checks": {k: rate_checks[k] for k in ("MATCH", "CONFLICT", "MISSING_OR_UNPARSEABLE")},
        "paired_coverage_pct": _pct_text(Decimal(n) * 100 / len(rows)) if rows else None,
        "positive_rows": sum(v > 0 for v in rates),
        "flat_rows": sum(v == 0 for v in rates),
        "negative_rows": sum(v < 0 for v in rates),
        "positive_share_of_paired_pct": _pct_text(Decimal(sum(v > 0 for v in rates)) * 100 / n) if n else None,
        "median_company_growth_pct": _pct_text(median(rates)) if rates else None,
        "aggregate_paired_growth_pct": _pct_text(pct(current_total, base_total)) if base_total else None,
        "paired_current_twd_thousands": current_total if n else None,
        "paired_base_twd_thousands": base_total if n else None,
        "target_current_share_of_paired_pct": (
            _pct_text(Decimal(target_current) * 100 / current_total)
            if target_current is not None and current_total else None),
        "target_share_of_paired_change_pct": (
            _pct_text(Decimal(target_current - target_base) * 100 / delta)
            if target_current is not None and target_base is not None and delta else None),
    }


def summarize_rows(rows: list[dict[str, str]]) -> dict:
    targets = [r for r in rows if r["公司代號"] == TARGET]
    if len(targets) != 1 or targets[0]["公司名稱"] != "台積電" or targets[0]["產業別"] != SECTOR:
        raise ValueError("TWSE_BREADTH_TARGET_SCOPE")
    sector = [r for r in rows if r["產業別"] == SECTOR]
    groups = {"all_observed": rows, "semiconductor_observed": sector,
              "semiconductor_ex_target": [r for r in sector if r["公司代號"] != TARGET]}
    if not groups["semiconductor_ex_target"]:
        raise ValueError("TWSE_BREADTH_PEERS_UNAVAILABLE")
    return {
        "observed_row_count": len(rows),
        "observed_industry_count": len({r["產業別"] for r in rows}),
        "groups": {key: {p: pair_summary(group, fields) for p, fields in PAIRS.items()}
                   for key, group in groups.items()},
        "aggregate_method": "RATIO_OF_MATCHED_NONNEGATIVE_AMOUNTS_WITH_POSITIVE_BASE",
        "median_method": "UNWEIGHTED_MEDIAN_OF_SAME_AMOUNT_PAIRS",
        "rate_reconciliation_tolerance_pp": "0.011",
        "unreconciled_rates_not_used_as_input": True,
        "amount_pairs_not_imputed": True,
    }


def _cutoff(operation: ExecutionOperation, context: WorkerContext) -> datetime:
    a, day = validate_event_cutoff(operation.parameters.get("as_of"))
    b, request_day = validate_event_cutoff(context.request_as_of)
    now = context.clock()
    if (day or request_day or not all(aware(v) for v in (a, b, now))
            or not VERIFIED <= a <= b <= now):
        raise ValueError("TWSE_ARCHIVE_EXACT_CUTOFF_REQUIRED_OR_NOT_YET_VERIFIED")
    return a


def run_twse_archive_industry(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    """Explicit one-snapshot profile; no general routing or external decision admission."""
    p = operation.parameters
    try:
        if (set(p) != EXPECTED_PARAMS or p.get("industry_profile") != PROFILE
                or p.get("archive_sha256") != DIGEST or p.get("market") != "TWSE"
                or p.get("subject_ids") != ["TWSE:2330"]
                or operation.evidence_domains != ["INDUSTRY_MACRO"]):
            raise ValueError("TWSE_ARCHIVE_PROFILE_SCOPE")
        cutoff = _cutoff(operation, context)
        raw = read_verified_artifact(ROOT, RELATIVE, DIGEST, SIZE)
        rows = read_rows(raw)
        if len(rows) != 1091:
            raise ValueError("TWSE_ARCHIVE_ROW_COUNT")
        summary = summarize_rows(rows)
    except (ValueError, OSError, UnicodeError, csv.Error) as exc:
        return OperationResult(operation_id=operation.operation_id, status="BLOCK",
                               exit_code=2, errors=[str(exc)])
    warnings = ["FIXED_OBSERVED_SNAPSHOT_NOT_COMPLETE_MARKET_OR_HISTORICAL_VINTAGE",
                "SOURCE_INDEPENDENCE_AND_ISSUER_FIRST_AVAILABILITY_NOT_VERIFIED",
                "NO_MAINLAND_SUPPLY_CHAIN_CAUSAL_LINK_OR_DECISION_AUTHORITY"]
    payload = {
        "profile": PROFILE, "market": "TWSE", "subject_id": "TWSE:2330", "industry_name": SECTOR,
        "as_of": cutoff.isoformat(), "request_as_of": context.request_as_of,
        "period": "2026-10", "provider_snapshot_date": "2026-11-17",
        "snapshot_is_not_publication_time": True,
        "actual_capture_at": OBSERVED.isoformat(), "durable_verified_at": VERIFIED.isoformat(),
        "capture_visible_at_cutoff": True, "source_sha256": DIGEST, "source_size_bytes": SIZE,
        "source_relative_path": RELATIVE, "source": "https://data.gov.tw/dataset/18420",
        "source_attribution": "金融監督管理委員會證券期貨局／臺灣證券交易所，2026，上市公司每月營業收入彙總表",
        "license": "https://data.gov.tw/license", "archive_rehash": "MATCH",
        "summary": summary, "warnings": warnings, "source_rowset_completeness_verified": False,
        "historical_membership_verified": False, "first_public_availability_verified": False,
        "historical_vintage_verified": False, "pit_safe": False,
        "decision_authority": False, "execution_allowed": False, "research_only": True,
    }
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    context.payloads[operation.operation_id] = payload
    return OperationResult(operation_id=operation.operation_id, status="WARN", exit_code=0,
        artifacts=[_artifact(path, media_type="application/json")], warnings=warnings,
        metrics={"profile": PROFILE, "observed_rows": len(rows), "source_sha256": DIGEST,
                 "capture_visible_at_cutoff": True, "pit_safe": False})
