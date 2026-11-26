"""Stock action reference against explicit public issuer events and second raw source."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from investment_evidence_engine.action_reference import (
    ActionObservation,
    acquire_action_observation,
    audit_cash_actions,
)
from investment_evidence_engine.historical_capture import SH, PublicSecurity, acquire_series
from investment_evidence_engine.holding_risk import CashDistribution, CashDistributionInputs
from investment_evidence_engine.market_calendar import acquire_calendar

FIRST=date(2025,11,25)
LAST=date(2026,11,25)


def main():
    subject=PublicSecurity(symbol="600519",asset_type="STOCK")
    try:
        observed=acquire_action_observation(subject,FIRST,LAST)
        calendar=acquire_calendar(FIRST,LAST)
        other=acquire_series("tencent",subject,FIRST,LAST)
    except (ValueError,OSError) as exc:
        print(json.dumps({"status":"BLOCKED","error_type":type(exc).__name__,"detail":str(exc)[:120]}))
        return 2
    events=CashDistributionInputs(events=(
        CashDistribution(subject_id=subject.symbol,disclosed_date=date(2025,12,11),ex_date=date(2025,12,19),
            gross_cash_per_unit_cny=23.957,
            source_locator="https://static.cninfo.com.cn/finalpage/2025-12-11/1224867074.PDF#page=1"),
        CashDistribution(subject_id=subject.symbol,disclosed_date=date(2026,6,22),ex_date=date(2026,6,26),
            gross_cash_per_unit_cny=28.02423,
            source_locator="https://static.cninfo.com.cn/finalpage/2026-06-22/1225379934.PDF#page=1"),
    ))
    with TemporaryDirectory() as tmp:
        path=Path(tmp)/"normalized_action_observation.json"
        raw=observed.model_dump_json().encode()
        path.write_bytes(raw)
        reopened=path.read_bytes()
        assert hashlib.sha256(reopened).digest()==hashlib.sha256(raw).digest()
        loaded=ActionObservation.model_validate_json(reopened)
        result=audit_cash_actions(loaded,other,calendar,events,now=datetime.now(SH))
        assert result["normalized_observation_sha256"]==hashlib.sha256(reopened).hexdigest()
        result["normalized_observation_rehash"]="MATCH"
    print(json.dumps(result))
    return 0 if result["status"]=="OBSERVED_ACTION_INTERVAL_RECONCILED" else 2


if __name__=="__main__":
    raise SystemExit(main())
