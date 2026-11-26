from datetime import UTC, date, datetime

import pytest

from investment_evidence_engine.action_reference import (
    ActionObservation,
    AdjustmentDateRow,
    PreviousCloseRow,
    audit_cash_actions,
)
from investment_evidence_engine.historical_capture import PublicSecurity
from investment_evidence_engine.historical_reference import DailyClose, HistoricalCloseSeries
from investment_evidence_engine.holding_risk import CashDistribution, CashDistributionInputs
from investment_evidence_engine.market_calendar import CalendarObservation, scheduled_days

START=date(2026,10,26)
END=date(2026,11,25)
NOW=datetime(2026,11,26,5,tzinfo=UTC)
CAL=CalendarObservation(first_requested=START,last_requested=END,observed_at=NOW,
                        rows=scheduled_days(START,END))
DAYS=tuple(row.day for row in CAL.rows if row.is_trading_day)
SUB=PublicSecurity(symbol="600000",asset_type="STOCK")
ACTION=DAYS[7]


def fixture():
    obs=ActionObservation(subject=SUB,first_requested=START,last_requested=END,observed_at=NOW,
        raw_rows=tuple(PreviousCloseRow(session=d,close=100. if d<ACTION else 90.,
                                       previous_reference=100. if d<ACTION else 90.) for d in DAYS),
        factors=(AdjustmentDateRow(effective_date=ACTION,forward_factor=.9,backward_factor=1/.9,
                                  adjustment_factor=.9),))
    series=HistoricalCloseSeries(subject_id=SUB.symbol,currency="CNY",source_label="tencent",price_basis="RAW_CLOSE",
        closes=tuple(DailyClose(session=r.session,close=r.close) for r in obs.raw_rows))
    events=CashDistributionInputs(events=(CashDistribution(subject_id=SUB.symbol,disclosed_date=DAYS[6],
        ex_date=ACTION,gross_cash_per_unit_cny=10.,source_locator="https://example.invalid/cash"),))
    return obs,series,events


def test_cash_only_reconciliation_is_not_completeness_attestation():
    obs,series,events=fixture()
    result=audit_cash_actions(obs,series,CAL,events,now=NOW)
    assert result["status"]=="OBSERVED_ACTION_INTERVAL_RECONCILED"
    assert result["event_audit"][0]["expected_cash_only_reference"]==90.
    assert result["event_audit"][0]["status"]=="CASH_ONLY_REFERENCE_MATCH"
    assert not result["corporate_action_coverage_verified"] and not result["decision_authority"]


@pytest.mark.parametrize("fault",["missing_event","wrong_cash","missing_factor","factor_without_event","wrong_reference"])
def test_unexplained_action_blocks(fault):
    obs,series,events=fixture()
    if fault=="missing_event":
        events=CashDistributionInputs(events=())
    elif fault=="wrong_cash":
        events=CashDistributionInputs(events=(events.events[0].model_copy(update={"gross_cash_per_unit_cny":9.}),))
    elif fault=="missing_factor":
        obs=obs.model_copy(update={"factors":()})
    elif fault=="factor_without_event":
        extra=obs.factors[0].model_copy(update={"effective_date":DAYS[8]})
        obs=obs.model_copy(update={"factors":obs.factors+(extra,)})
    elif fault=="wrong_reference":
        rows=list(obs.raw_rows)
        rows[7]=rows[7].model_copy(update={"previous_reference":95.})
        obs=obs.model_copy(update={"raw_rows":tuple(rows)})
    assert audit_cash_actions(obs,series,CAL,events,now=NOW)["status"]=="BLOCKED"


def test_mismatched_close_and_session_rejected():
    obs,series,events=fixture()
    with pytest.raises(ValueError,match="CROSSCHECK"):
        audit_cash_actions(obs,series.model_copy(update={"closes":(series.closes[0].model_copy(update={"close":101.}),)+series.closes[1:]}),
                           CAL,events,now=NOW)
    with pytest.raises(ValueError,match="SESSION"):
        audit_cash_actions(obs,series.model_copy(update={"closes":series.closes[1:]}),CAL,events,now=NOW)
