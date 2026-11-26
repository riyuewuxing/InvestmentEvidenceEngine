"""Exact raw snapshot digest matching, not authentication or semantic admission."""
from __future__ import annotations

import hashlib
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
