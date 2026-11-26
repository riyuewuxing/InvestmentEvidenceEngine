"""Verify exact public scan attachment bytes; no upstream/PIT admission authority."""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

from .contracts import InputArtifactRef, ObservedInputArtifact, _find_private_parameter, canonical_sha256
from .snapshot_integrity import strict_json_loads
from .transport_integrity import observe_artifact_file, read_contract_bytes

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


def observe_scan_input(root: Path, ref: InputArtifactRef) -> tuple[ObservedInputArtifact, bytes]:
    digest, size = observe_artifact_file(
        root, ref.materialized_path, ref.source_artifact_size_bytes, max_bytes=4 * 1024 * 1024)
    if digest != ref.source_artifact_sha256:
        raise ValueError("INPUT_ARTIFACT_HASH_MISMATCH")
    raw = read_contract_bytes(root / ref.materialized_path)
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("INPUT_ARTIFACT_CHANGED")
    data = strict_json_loads(raw)
    if (not isinstance(data, dict) or not set(data).issubset(_SCAN_KEYS)
            or _find_private_parameter(data)
            or data.get("ranking_semantics") != "RESEARCH_PRIORITY_NOT_RETURN_FORECAST"
            or data.get("research_only") is not True or data.get("decision_authority") is not False
            or data.get("pit_safe") is not False or data.get("input_mode") != "LIVE_MARKET_UNIVERSE"):
        raise ValueError("INPUT_ARTIFACT_NOT_PUBLIC_SCAN_RESEARCH")
    dep = data.get("dependency_evidence")
    if (not isinstance(dep, dict) or dep.get("as_of") != ref.as_of
            or dep.get("market") != "CN_A" or dep.get("asset_type") != "STOCK"):
        raise ValueError("INPUT_ARTIFACT_DEPENDENCY_SCOPE_MISMATCH")
    rows = data.get("candidates")
    if (not isinstance(rows, list) or not 1 <= len(rows) <= 1000
            or type(data.get("candidate_count")) is not int or data["candidate_count"] != len(rows)):
        raise ValueError("INPUT_ARTIFACT_CANDIDATE_COUNT_INVALID")
    codes = set()
    for row in rows:
        if not isinstance(row, dict) or not set(row).issubset(_RECORD_KEYS):
            raise ValueError("INPUT_ARTIFACT_CANDIDATE_FIELDS_INVALID")
        code = row.get("code")
        if (not isinstance(code, str) or re.fullmatch(r"[0-9]{6}", code) is None
                or code in codes or row.get("asset", code) != code):
            raise ValueError("INPUT_ARTIFACT_CANDIDATE_IDENTITY_INVALID")
        codes.add(code)
        for key, value in row.items():
            if key in {"asset", "code", "name"}:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("INPUT_ARTIFACT_CANDIDATE_TEXT_INVALID")
            elif value is not None and (type(value) not in {int, float} or not math.isfinite(value)):
                raise ValueError("INPUT_ARTIFACT_CANDIDATE_NUMBER_INVALID")
    if rows[0]["code"] != ref.selector.value or canonical_sha256(rows[0]) != ref.selector.record_sha256:
        raise ValueError("INPUT_ARTIFACT_RECORD_SELECTOR_MISMATCH")
    observed = ObservedInputArtifact(input_id=ref.input_id, materialized_path=ref.materialized_path,
                                    observed_sha256=digest, observed_size_bytes=size, status="MATCH")
    return observed, raw
