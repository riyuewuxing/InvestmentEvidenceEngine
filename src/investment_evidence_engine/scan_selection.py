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



def verify_scan_derivation(raw_universe: bytes, raw_scan: bytes, *, as_of: str,
                           requested_rules: object, universe_status: str, top_n: object = 50) -> dict:
    """Independently verify the stable ranking and row projection of a sealed public scan.

    This is a pure arithmetic/lineage check over observed normalized bytes.
    Neither the universe's original provenance nor historical membership is established.
    """
    selected = select_scan_record(raw_scan, as_of)
    scan = strict_json_loads(raw_scan)
    universe = strict_json_loads(raw_universe)
    if (not isinstance(universe, dict) or universe.get("as_of") != as_of
            or universe.get("market") != "CN_A" or universe.get("asset_type") != "STOCK"
            or universe.get("source") != "public_market_data"
            or universe.get("public_data_only") is not True
            or universe.get("decision_authority") is not False):
        raise ValueError("SCAN_DERIVATION_UNIVERSE_SCOPE")
    if universe_status not in {"PASS", "WARN"}:
        raise ValueError("SCAN_DERIVATION_DEPENDENCY_STATUS")
    listing = universe.get("listing_crosscheck")
    listing_status = listing.get("status") if isinstance(listing, dict) else None
    expected_dependency = {"operation_id": "market-universe", "kind": "MARKET_UNIVERSE",
        "status": universe_status, "as_of": as_of, "market": "CN_A", "asset_type": "STOCK",
        "source": "public_market_data", "provider": universe.get("provider"),
        "primary_provider": universe.get("primary_provider"),
        "quote_trade_date_status": universe.get("quote_trade_date_status"),
        "listing_crosscheck": {"status": listing_status}}
    for key in ("quality_flags", "warnings"):
        values = universe.get(key, [])
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ValueError("SCAN_DERIVATION_DEPENDENCY_METADATA")
        expected_dependency[key] = values[:16]
    if scan["dependency_evidence"] != expected_dependency:
        raise ValueError("SCAN_DERIVATION_DEPENDENCY_METADATA")
    if type(top_n) is not int or not 1 <= top_n <= 1000:
        raise ValueError("SCAN_DERIVATION_TOP_N")
    rules = scan["rules"]
    if not isinstance(requested_rules, list) or len(requested_rules) != len(rules):
        raise ValueError("SCAN_DERIVATION_REQUEST_RULES")
    for req, actual in zip(requested_rules, rules, strict=True):
        if (not isinstance(req, dict) or not set(req).issubset({"field", "operator", "threshold", "weight"})
                or type(req.get("threshold")) not in {int, float}
                or type(req.get("weight", 1)) not in {int, float}
                or actual != {**req, "weight": req.get("weight", 1)}):
            raise ValueError("SCAN_DERIVATION_REQUEST_RULES")
    rows = universe.get("records")
    if not isinstance(rows, list) or not rows or not all(isinstance(row, dict) for row in rows):
        raise ValueError("SCAN_DERIVATION_UNIVERSE_ROWS")
    if (type(scan.get("screened_count")) is not int or scan["screened_count"] != len(rows)
            or scan["candidate_count"] != min(top_n, len(rows))):
        raise ValueError("SCAN_DERIVATION_COUNT")
    columns = set(rows[0])
    fields = _RECORD_KEYS - {"matched_rule_count", "research_priority_score"}
    if not {"code", "asset"} <= columns or not columns <= fields:
        raise ValueError("SCAN_DERIVATION_UNIVERSE_FIELDS")
    seen = set()
    finite_rule_fields = set()
    ranked = []
    for index, row in enumerate(rows):
        code = row.get("code")
        if (set(row) != columns or not isinstance(code, str) or re.fullmatch(r"[0-9]{6}", code) is None
                or code in seen or row["asset"] != code):
            raise ValueError("SCAN_DERIVATION_UNIVERSE_IDENTITY")
        seen.add(code)
        for key, value in row.items():
            if key in {"code", "asset", "name"}:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("SCAN_DERIVATION_UNIVERSE_TEXT")
            elif value is not None and (type(value) not in {int, float} or not math.isfinite(value)):
                raise ValueError("SCAN_DERIVATION_UNIVERSE_NUMBER")
        score = 0.0
        matches = 0
        for rule in rules:
            field = rule["field"]
            if field not in row:
                raise ValueError("SCAN_DERIVATION_RULE_FIELD")
            value = row[field]
            if value is None:
                continue
            finite_rule_fields.add(field)
            x, threshold = float(value), float(rule["threshold"])
            op = rule["operator"]
            hit = ((op == "GT" and x > threshold) or (op == "GE" and x >= threshold)
                   or (op == "LT" and x < threshold) or (op == "LE" and x <= threshold))
            if hit:
                score += float(rule["weight"])
                matches += 1
        if not math.isfinite(score):
            raise ValueError("SCAN_DERIVATION_SCORE_NONFINITE")
        ranked.append((score, matches, index, row))
    if finite_rule_fields != {rule["field"] for rule in rules}:
        raise ValueError("SCAN_DERIVATION_RULE_FIELD_NO_NUMERIC")
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
    for candidate, (score, matches, _, source) in zip(scan["candidates"], ranked[:top_n], strict=True):
        if set(candidate) != columns | {"matched_rule_count", "research_priority_score"}:
            raise ValueError("SCAN_DERIVATION_CANDIDATE_FIELDS")
        if any(candidate[key] != value for key, value in source.items()):
            raise ValueError("SCAN_DERIVATION_ROW_MISMATCH")
        # pandas record JSON serializes floating point with ten decimal places.
        # The rank above is from unrounded score; this tolerance is only for
        # serialized score comparison, not for determining candidate order.
        observed_score = candidate["research_priority_score"]
        if (type(observed_score) not in {int, float}
                or abs(observed_score - score) > 5.1e-10
                or candidate["matched_rule_count"] != matches):
            raise ValueError("SCAN_DERIVATION_SCORE_MISMATCH")
    return {"status": "MATCH", "selected": selected, "screened_count": len(rows),
            "candidate_count": scan["candidate_count"], "stable_tie_order_verified": True,
            "dependency_metadata_matches_observed_universe": True,
            "historical_membership_verified": False, "pit_safe": False, "decision_authority": False}
