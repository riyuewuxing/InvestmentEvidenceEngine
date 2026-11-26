"""Exact raw snapshot digest matching, not authentication or semantic admission."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping


def raw_snapshot_matches(observed: Mapping[str, bytes], expected: Mapping[str, str],
                         *, required: frozenset[str]) -> bool:
    if not required or set(observed) != required or set(expected) != required:
        return False
    for key in required:
        body, digest = observed[key], expected[key]
        if (not isinstance(body, bytes) or not body or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or hashlib.sha256(body).hexdigest() != digest):
            return False
    return True


def verify_json_snapshot_fields(
    raw: bytes,
    expected_sha256: str,
    fields: Mapping[tuple[str, ...], object],
) -> dict:
    """Rehash a retained JSON document and match required typed fields.

    This is content binding, not proof of the document's origin, freshness,
    execution authority, or completeness outside the specified contract.
    """
    if not raw_snapshot_matches({"report": raw}, {"report": expected_sha256},
                                required=frozenset({"report"})):
        raise ValueError("REPORT_DIGEST_MISMATCH")
    if not fields:
        raise ValueError("REPORT_FIELDS_REQUIRED")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("REPORT_DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValueError("REPORT_NONFINITE_JSON")

    document = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                          parse_constant=invalid_constant)
    if not isinstance(document, dict):
        raise ValueError("REPORT_OBJECT_REQUIRED")
    for path, expected in fields.items():
        if not isinstance(path, tuple) or not path or any(
            not isinstance(key, str) or not key for key in path
        ):
            raise ValueError("REPORT_FIELD_PATH_INVALID")
        actual = document
        for key in path:
            if not isinstance(actual, dict) or key not in actual:
                raise ValueError("REPORT_FIELD_MISSING:" + ".".join(path))
            actual = actual[key]
        if type(actual) is not type(expected) or actual != expected:
            raise ValueError("REPORT_FIELD_MISMATCH:" + ".".join(path))
    return document
