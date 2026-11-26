"""Bounded public controls, no private inputs or provider records uploaded."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from investment_evidence_engine.historical_capture import PublicSecurity, observe_pair
from investment_evidence_engine.historical_receipt import (
    HistoricalCaptureFailure,
    HistoricalReceipt,
    load_receipt,
    persist_receipt,
)


def main() -> int:
    end = date(2026, 11, 25)
    start = end - timedelta(days=95)
    candidate = PublicSecurity(symbol="600519", asset_type="STOCK")
    alternative = PublicSecurity(symbol="510050", asset_type="ETF")
    summary, sources = observe_pair(candidate, alternative, start, end,
        providers=("sina", "baostock", "tencent"))
    summary["provider_package_version"] = version("akshare")
    summary["normalized_input_sha256"] = {
        f"{series.subject_id}:{series.source_label}": hashlib.sha256(series.model_dump_json().encode()).hexdigest()
        for series in sources
    }
    if sources:
        receipt = HistoricalReceipt(candidate=candidate, alternative=alternative,
            first_requested=start, last_completed=end, observed_at=datetime.fromisoformat(summary["observed_at"]),
            akshare_version=summary["provider_package_version"],
            attempted_providers=tuple(summary["attempted_providers"]),
            failures=tuple(HistoricalCaptureFailure.model_validate(f) for f in summary["failures"]),
            series=sources)
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            digest, computed = persist_receipt(folder, receipt)
            loaded = load_receipt(folder, candidate, alternative, end, now=datetime.now(ZoneInfo("Asia/Shanghai")))
            assert loaded["normalized_observation_sha256"] == digest
            assert loaded["normalized_observation_rehashed"] is True
            assert loaded["status"] == computed["status"] == summary["status"]
            assert loaded.get("reference") == computed.get("reference") == summary.get("reference")
            assert loaded["failures"] == summary["failures"]
            assert loaded["attempted_providers"] == summary["attempted_providers"]
            summary["normalized_receipt_sha256"] = digest
            summary["normalized_receipt_rehash"] = "MATCH"
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "OBSERVED_REFERENCE_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
