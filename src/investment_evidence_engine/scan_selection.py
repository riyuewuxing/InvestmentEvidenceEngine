"""Public-only scan selection schema shared between executor and consumer.

Validates the actual candidate packet, not historical source provenance or admission.
"""
from __future__ import annotations

import math
import re

from .snapshot_integrity import strict_json_loads

_RECORD_KEYS = {
    "amount", "asset", "code", "float_market_cap", "latest_price", "matched_rule_count",
    "name", "pb", "pct_change", "pe_dynamic", "research_priority_score", "total_market_cap",
    "turnover_rate", "volume", "amplitude", "change_60d", "ytd_change",
}
_SCAN_KEYS = {
    "candidates", "rules", "candidate_count", "ranking_semantics", "input_mode",
    "rule_origin", "screened_count", "research_only", "pit_safe", "decision_authority",
    "dependency_evidence",
}


_DEPENDENCY_KEYS = {
    "operation_id", "kind", "status", "as_of", "market", "asset_type", "source",
    "provider", "primary_provider", "quote_trade_date_status", "listing_crosscheck",
    "quality_flags", "warnings",
}


def select_scan_record(raw: bytes, as_of: str) -> dict:
    """Validate actual public scan bytes; return first record, not an admission."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 4 * 1024 * 1024:
        raise ValueError("INPUT_ARTIFACT_BODY_INVALID")
    data = strict_json_loads(raw)
    if (not isinstance(data, dict) or not set(data).issubset(_SCAN_KEYS)
            or data.get("ranking_semantics") != "RESEARCH_PRIORITY_NOT_RETURN_FORECAST"
            or data.get("research_only") is not True or data.get("decision_authority") is not False
            or data.get("pit_safe") is not False or data.get("input_mode") != "LIVE_MARKET_UNIVERSE"):
        raise ValueError("INPUT_ARTIFACT_NOT_PUBLIC_SCAN_RESEARCH")
    rules = data.get("rules")
    if (data.get("rule_origin") != "SYSTEM_RESEARCH_FILTER"
            or not isinstance(rules, list) or not 1 <= len(rules) <= 32):
        raise ValueError("INPUT_ARTIFACT_PUBLIC_RULES_REQUIRED")
    fields = _RECORD_KEYS - {"asset", "code", "name", "research_priority_score", "matched_rule_count"}
    for rule in rules:
        if (not isinstance(rule, dict) or set(rule) != {"field", "operator", "threshold", "weight"}
                or rule["field"] not in fields or rule["operator"] not in {"GT", "GE", "LT", "LE"}
                or any(type(rule[key]) not in {int, float} or not math.isfinite(rule[key])
                       for key in ("threshold", "weight")) or rule["weight"] < 0):
            raise ValueError("INPUT_ARTIFACT_PUBLIC_RULE_INVALID")
    dep = data.get("dependency_evidence")
    if (not isinstance(dep, dict) or not set(dep).issubset(_DEPENDENCY_KEYS)
            or dep.get("as_of") != as_of
            or dep.get("market") != "CN_A" or dep.get("asset_type") != "STOCK"
            or dep.get("source") != "public_market_data"
            or dep.get("status") not in {"PASS", "WARN"}):
        raise ValueError("INPUT_ARTIFACT_DEPENDENCY_SCOPE_MISMATCH")
    if ("kind" in dep and dep["kind"] != "MARKET_UNIVERSE") or (
            "operation_id" in dep and (not isinstance(dep["operation_id"], str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", dep["operation_id"]))):
        raise ValueError("INPUT_ARTIFACT_DEPENDENCY_IDENTITY_INVALID")
    for key in ("provider", "primary_provider", "quote_trade_date_status"):
        value = dep.get(key)
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,80}", value)):
            raise ValueError("INPUT_ARTIFACT_DEPENDENCY_TEXT_INVALID")
    if "listing_crosscheck" in dep:
        listing = dep["listing_crosscheck"]
        if (not isinstance(listing, dict) or set(listing) != {"status"}
                or (listing["status"] is not None and (not isinstance(listing["status"], str)
                or not re.fullmatch(r"[A-Z_]{1,80}", listing["status"])))):
            raise ValueError("INPUT_ARTIFACT_LISTING_METADATA_INVALID")
    for key in ("warnings", "quality_flags"):
        if key in dep and (not isinstance(dep[key], list) or len(dep[key]) > 16 or any(
                not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9_:.<>=-]{1,160}", value)
                for value in dep[key])):
            raise ValueError("INPUT_ARTIFACT_DEPENDENCY_WARNING_INVALID")
    rows = data.get("candidates")
    if (not isinstance(rows, list) or not 1 <= len(rows) <= 1000
            or type(data.get("candidate_count")) is not int or data["candidate_count"] != len(rows)):
        raise ValueError("INPUT_ARTIFACT_CANDIDATE_COUNT_INVALID")
    if "screened_count" in data and (type(data["screened_count"]) is not int
            or data["screened_count"] < len(rows)):
        raise ValueError("INPUT_ARTIFACT_SCREENED_COUNT_INVALID")
    codes = set()
    for row in rows:
        if not isinstance(row, dict) or not set(row).issubset(_RECORD_KEYS):
            raise ValueError("INPUT_ARTIFACT_CANDIDATE_FIELDS_INVALID")
        code = row.get("code")
        if (not isinstance(code, str) or re.fullmatch(r"[0-9]{6}", code) is None
                or code in codes or row.get("asset", code) != code):
            raise ValueError("INPUT_ARTIFACT_CANDIDATE_IDENTITY_INVALID")
        codes.add(code)
        if "matched_rule_count" in row and (type(row["matched_rule_count"]) is not int
                or not 0 <= row["matched_rule_count"] <= len(rules)):
            raise ValueError("INPUT_ARTIFACT_MATCHED_COUNT_INVALID")
        for key, value in row.items():
            if key in {"asset", "code", "name"}:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("INPUT_ARTIFACT_CANDIDATE_TEXT_INVALID")
            elif value is not None and (type(value) not in {int, float} or not math.isfinite(value)):
                raise ValueError("INPUT_ARTIFACT_CANDIDATE_NUMBER_INVALID")
    return rows[0]
