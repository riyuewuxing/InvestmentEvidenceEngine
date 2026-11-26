"""Conservative cross-provider mainland stock-code overlap diagnostic.

A code-set comparison does not certify listing completeness, quote dates,
prices, point-in-time availability, or independence of ultimate upstreams.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

_SH = frozenset({"600", "601", "603", "605", "688", "689"})
_SZ = frozenset({"000", "001", "002", "003", "004", "300", "301", "302", "303"})
_CODE = re.compile(r"(?:(sh|sz|bj)\.?)?([0-9]{6})", re.ASCII)


def stock_code(raw: object, *, require_exchange: bool) -> str | None:
    if not isinstance(raw, str):
        raise ValueError("non-string security code")
    match = _CODE.fullmatch(raw.strip().lower())
    if match is None:
        raise ValueError("invalid security code")
    exchange, code = match.groups()
    if require_exchange and exchange is None:
        raise ValueError("missing exchange prefix")
    expected = "sh" if code[:3] in _SH else "sz" if code[:3] in _SZ else None
    # An exchange prefix is authoritative for scope. In particular, sh.000001
    # is an index and must never be interpreted as Shenzhen stock 000001.
    if expected is None or (exchange is not None and exchange != expected):
        return None
    return expected + "." + code


def normalize_codes(raw: object, *, require_exchange: bool) -> tuple[set[str], dict]:
    if not isinstance(raw, list) or not 0 < len(raw) <= 12_000:
        raise ValueError("empty or oversized security universe")
    counts = Counter()
    codes = set()
    for value in raw:
        try:
            code = stock_code(value, require_exchange=require_exchange)
        except ValueError:
            counts["invalid"] += 1
            continue
        if code is None:
            counts["out_of_scope"] += 1
        elif code in codes:
            counts["duplicate"] += 1
        else:
            codes.add(code)
    return codes, {
        "raw_count": len(raw), "unique_in_scope": len(codes),
        "invalid_count": counts["invalid"], "duplicate_count": counts["duplicate"],
        "out_of_scope_count": counts["out_of_scope"],
        "sh_count": sum(c.startswith("sh.") for c in codes),
        "sz_count": sum(c.startswith("sz.") for c in codes),
        "normalized_code_set_sha256": hashlib.sha256(
            json.dumps(sorted(codes), separators=(",", ":")).encode("ascii")
        ).hexdigest(),
    }


def compare_code_sets(reference: object, snapshot: object) -> dict:
    left, left_stats = normalize_codes(reference, require_exchange=True)
    right, right_stats = normalize_codes(snapshot, require_exchange=False)
    clean = all(s["invalid_count"] == 0 and s["duplicate_count"] == 0
                and min(s["sh_count"], s["sz_count"]) >= 1000
                for s in (left_stats, right_stats))
    return {
        "scope": "SH_SZ_A_STOCK_PREFIX_SUBSET_EXCLUDES_BSE",
        "status": ("MATCH_OBSERVED_SETS" if left == right else "DIFFERENT_OBSERVED_SETS")
        if clean else "BLOCK_INCOMPLETE_OR_AMBIGUOUS",
        "reference": left_stats, "snapshot": right_stats,
        "overlap": len(left & right), "reference_only": len(left - right),
        "snapshot_only": len(right - left),
        "listing_completeness_verified": False,
        "quote_trade_date_verified": False,
        "independent_price_source_verified": False,
        "source_independence_verified": False,
        "historical_vintage_verified": False,
        "decision_authority": False,
    }
