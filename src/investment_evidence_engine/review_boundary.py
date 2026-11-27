"""Narrow, negative-only checks shared by research and review consumers.

A matching digest authenticates neither a source nor a claim. In particular,
an engine receipt of a deleted source body is not itself that source body.
The asset code gate checks syntax/routing only, not listing or PIT identity.
"""
from __future__ import annotations

import hashlib
import re

from .snapshot_integrity import strict_json_loads

_STOCK_PREFIXES = {
    "sh": ("600", "601", "603", "605", "688", "689"),
    "sz": ("000", "001", "002", "003", "300", "301", "302"),
    "bj": ("43", "83", "87", "92"),
}
_NON_ORIGINAL_CLASSES = frozenset({
    "DYNAMIC_CARD_DECODED_INPUTS",
    "PUBLIC_CASE_OBSERVED_LOG_METADATA_ONLY",
})


def stock_review_scope(subject_id: object) -> str | None:
    """Return only a syntactically consistent stock route, never a verified identity.

    Bare numeric codes follow the existing stock-request routing convention.
    Explicit exchange mismatches, indices, ETFs and unknown code families
    cannot enter a stock-only review. Historical listing evidence is separate.
    """
    if not isinstance(subject_id, str):
        return None
    match = re.fullmatch(r"(?:(sh|sz|bj))?([0-9]{6})", subject_id)
    if match is None:
        return None
    explicit, code = match.groups()
    routes = [exchange for exchange, prefixes in _STOCK_PREFIXES.items()
              if code.startswith(prefixes)]
    if len(routes) != 1 or (explicit is not None and explicit != routes[0]):
        return None
    return routes[0] + code


def _metadata_only(document: dict) -> bool:
    if document.get("scope") in _NON_ORIGINAL_CLASSES or document.get("source_class") in _NON_ORIGINAL_CLASSES:
        return True
    # Explicit audit-only/vintage markers are meaningful at the document
    # level. Do not reject ordinary raw data merely because the producer is
    # not a decision authority (all public-engine results are non-authoritative).
    if (document.get("pit_eligible") is False or document.get("pit_safe") is False
            or document.get("admissible_for_decision") is False):
        return True
    # Recognize producer receipts that explicitly state raw bodies were not
    # retained. Nested older financial/pressure receipts may not have the
    # modern top-level authority flag; lack of source bytes is enough here.
    if isinstance(document.get("executor_commit"), str) and (
            document.get("raw_body_retained") is False
            or document.get("raw_provider_bytes_retained") is False
            or document.get("raw_vendor_bodies_retained") is False):
        return True
    return False


def original_support_blocker(raw: bytes, *, source_class: str, expected_sha256: str) -> str | None:
    """Negative check for a proposed original supporting artifact.

    No positive source/PIT/admission assertion. Do not use as a substitute
    for the existing document store, explicit claim review, source times,
    or provenance verification. Cannot detect content stripped of all
    provenance markers or a maliciously re-authored source.
    """
    if (not isinstance(raw, bytes) or not raw or not isinstance(expected_sha256, str)
            or hashlib.sha256(raw).hexdigest() != expected_sha256):
        return "SUPPORT_BYTES_MISMATCH"
    if not isinstance(source_class, str) or not source_class.strip():
        return "SUPPORT_CLASS_UNKNOWN"
    if source_class.strip().upper() in _NON_ORIGINAL_CLASSES:
        return "SUPPORT_METADATA_ONLY"
    # Non-JSON formats retain their existing source-specific validation.
    # Handle a UTF-8 BOM explicitly; do not let it hide JSON audit markers.
    probe = raw.removeprefix(b"\xef\xbb\xbf").lstrip()
    if not probe.startswith((b"{", b"[")):
        return None
    try:
        document = strict_json_loads(probe)
        if isinstance(document, dict) and _metadata_only(document):
            return "SUPPORT_METADATA_ONLY"
        if isinstance(document, list) and any(
                isinstance(item, dict) and _metadata_only(item) for item in document):
            return "SUPPORT_METADATA_ONLY"
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return "SUPPORT_JSON_INVALID"
    return None
