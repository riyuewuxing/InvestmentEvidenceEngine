"""Read-only validation of exact append replay against an observed journal prefix.

No storage, locking, event construction or authority is provided here. The caller
must verify the journal chain, bind the entire plan in its first entry, and use
an atomic compare-and-append operation for each missing entry.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


def _canonical(entry: Mapping[str, Any]) -> str:
    return json.dumps(dict(entry), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _identity(entry: Mapping[str, Any]) -> str:
    value = entry.get("event_id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("append replay requires a nonempty event_id")
    return value


def resume_prefix_length(
    planned: Sequence[Mapping[str, Any]],
    observed: Sequence[Mapping[str, Any]],
) -> int:
    """Return an exact completed count; incomplete replay requires a tip prefix.

    Compare canonical JSON, not loose Python equality (e.g. True == 1).
    The first planned row must be a caller-defined full-plan commitment.
    A complete replay is read-only even if unrelated later entries exist.
    """
    if not planned:
        raise ValueError("append replay requires a nonempty plan")
    keys = [_identity(entry) for entry in planned]
    if len(set(keys)) != len(keys):
        raise ValueError("append replay plan contains duplicate event_id")
    positions: dict[str, tuple[int, Mapping[str, Any]]] = {}
    for index, row in enumerate(observed):
        key = _identity(row)
        if key in positions:
            raise ValueError("append replay observed duplicate event_id")
        positions[key] = index, row
    prefix: list[int] = []
    missing = False
    for key, entry in zip(keys, planned, strict=True):
        encoded = _canonical(entry)
        if key not in positions:
            missing = True
            continue
        index, actual = positions[key]
        if missing or _canonical(actual) != encoded:
            raise ValueError("append replay conflicts with immutable event")
        prefix.append(index)
    if prefix and prefix != list(range(prefix[0], prefix[0] + len(prefix))):
        raise ValueError("append replay prefix is not contiguous")
    if prefix and len(prefix) < len(planned) and prefix[-1] != len(observed) - 1:
        raise ValueError("interrupted append replay is not at current journal tip")
    return len(prefix)
