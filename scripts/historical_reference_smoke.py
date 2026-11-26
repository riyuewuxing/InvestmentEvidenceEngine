"""Bounded public controls, no private inputs or provider records uploaded."""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from importlib.metadata import version

from investment_evidence_engine.historical_capture import PublicSecurity, observe_pair


def main() -> int:
    end = date(2026, 11, 25)
    start = end - timedelta(days=95)
    summary, sources = observe_pair(PublicSecurity(symbol="600519", asset_type="STOCK"),
        PublicSecurity(symbol="510050", asset_type="ETF"), start, end,
        providers=("sina", "baostock", "tencent"))
    summary["provider_package_version"] = version("akshare")
    summary["normalized_input_sha256"] = {
        f"{series.subject_id}:{series.source_label}": hashlib.sha256(series.model_dump_json().encode()).hexdigest()
        for series in sources
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "OBSERVED_REFERENCE_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
