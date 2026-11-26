"""Supplemental independent vendor audit of the already frozen public pilot.

Does not change its preregistration, prediction, selection or outcome.
Only five exact unadjusted date/open/close observations are printed.
"""
from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal

SYMBOL = "sh600519"
DAYS = ("2026-11-19", "2026-11-20", "2026-11-23", "2026-11-24", "2026-11-25")


def canonical_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def normalize(payload: dict) -> list[list[str]]:
    rows = payload["data"][SYMBOL]["day"]
    if not isinstance(rows, list) or len(rows) > 756:
        raise ValueError("AUDIT_RAW_DAY_SCHEMA")
    selected = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6 or not isinstance(row[0], str):
            raise ValueError("AUDIT_ROW_SCHEMA")
        if row[0] not in DAYS:
            continue
        if any(not isinstance(x, str) for x in row[1:5]):
            raise ValueError("AUDIT_PRICE_SCHEMA")
        op, close, high, low = map(Decimal, row[1:5])
        if (any(not x.is_finite() or x <= 0 for x in (op, close, high, low))
                or not low <= min(op, close) <= max(op, close) <= high):
            raise ValueError("AUDIT_PRICE_RANGE")
        selected.append([row[0], row[1], row[2]])
    if tuple(row[0] for row in selected) != DAYS:
        raise ValueError("AUDIT_INCOMPLETE_DUPLICATE_OR_UNORDERED")
    return selected


def main() -> int:
    started = datetime.now(UTC)
    try:
        param = f"{SYMBOL},day,{DAYS[0]},{DAYS[-1]},32,"
        url = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?" + urllib.parse.urlencode({"param": param})
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(2*1024*1024+1)
        if len(raw) > 2*1024*1024:
            raise ValueError("AUDIT_BODY_LIMIT")
        selected = normalize(json.loads(raw))
    except Exception as exc:
        print("PUBLIC_PILOT_AUDIT_BLOCKED " + type(exc).__name__)
        return 2
    receipt = {
        "audit_scope": "SUPPLEMENTAL_ONLY_NO_REFREEZE",
        "source": "tencent_raw_day",
        "subject_id": "600519",
        "fields": ["session", "open", "close"],
        "rows": selected,
        "started_at": started.isoformat(),
        "observed_at": datetime.now(UTC).isoformat(),
        "raw_vendor_body_archived": False,
        "independent_upstream_proven": False,
        "research_only": True,
        "execution_allowed": False,
    }
    data = canonical_bytes(receipt)
    print("PUBLIC_PILOT_AUDIT_RECEIPT " + data.decode("utf-8"))
    print("PUBLIC_PILOT_AUDIT_SHA256 " + hashlib.sha256(data).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
