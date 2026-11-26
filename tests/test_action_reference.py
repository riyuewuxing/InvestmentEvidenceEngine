from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from investment_evidence_engine.action_reference import (
    ActionObservation,
    AdjustmentDateRow,
    PreviousCloseRow,
    audit_cash_actions,
    bind_cash_reference_terms,
)
from investment_evidence_engine.cash_entitlement import CashEntitlementTerms
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


def reference_fixture():
    obs, series, _ = fixture()
    # Synthetic close at 5.00; cent rounding separates 0.0352 from 0.0336129.
    rows = tuple(PreviousCloseRow(session=d, close=5.0 if d<ACTION else 4.97,
                    previous_reference=5.0 if d<ACTION else 4.97) for d in DAYS)
    obs = obs.model_copy(update={"raw_rows": rows})
    series = series.model_copy(update={"closes":tuple(DailyClose(session=r.session,close=r.close)
                                                     for r in rows)})
    locator = "https://example.invalid/cash"
    terms = CashEntitlementTerms(symbol=SUB.symbol, disclosed_date=DAYS[6], record_date=DAYS[6],
        ex_date=ACTION, source_locator=locator, total_shares=2500783182, excluded_shares=112750413,
        gross_per_share=Decimal("0.0352"), declared_total_cash=Decimal("84058753.47"),
        declared_reference_deduction=Decimal("0.0336129"))
    events = CashDistributionInputs(events=(CashDistribution(subject_id=SUB.symbol,
        disclosed_date=DAYS[6], ex_date=ACTION, gross_cash_per_unit_cny=0.0352,
        source_locator=locator),))
    return obs, series, events, terms


def test_explicit_reference_deduction_does_not_replace_gross_cash():
    obs, series, events, terms = reference_fixture()
    legacy = audit_cash_actions(obs, series, CAL, events, now=NOW)
    assert legacy["status"] == "BLOCKED"
    assert legacy["event_audit"][0]["expected_cash_only_reference"] == 4.96
    assert legacy["event_audit"][0]["reference_deduction_basis"] == "ASSUMED_EQUAL_TO_GROSS_ENTITLEMENT"
    result = audit_cash_actions(obs, series, CAL, events, now=NOW, reference_terms=(terms,))
    assert result["status"] == "OBSERVED_ACTION_INTERVAL_RECONCILED"
    row = result["event_audit"][0]
    assert row["expected_cash_only_reference"] == 4.97
    assert row["cash_event_gross_cny"] == 0.0352
    assert row["reference_deduction_cny"] == "0.0336129"
    assert result["all_included_cash_reference_terms_explicit"]
    assert not result["historical_vintage_verified"] and not result["decision_authority"]


@pytest.mark.parametrize("fault", ["duplicate", "symbol", "locator", "record", "missing_event"])
def test_explicit_reference_terms_bind_exact_cash_event(fault):
    obs, series, events, terms = reference_fixture()
    supplied = (terms,)
    if fault == "duplicate":
        supplied = (terms, terms)
    elif fault == "symbol":
        supplied = (replace(terms, symbol="000035"),)
    elif fault == "locator":
        supplied = (replace(terms, source_locator="https://example.invalid/other"),)
    elif fault == "record":
        supplied = (replace(terms, disclosed_date=DAYS[5], record_date=DAYS[5]),)
    else:
        events = CashDistributionInputs(events=())
    with pytest.raises(ValueError, match="ACTION_REFERENCE_TERMS_SCOPE"):
        audit_cash_actions(obs, series, CAL, events, now=NOW, reference_terms=supplied)


def test_preflight_checks_exact_included_terms_before_source_acquisition():
    _, _, events, terms = reference_fixture()
    included, excluded, explicit = bind_cash_reference_terms(events, SUB, DAYS, (terms,))
    assert not excluded and set(included) == set(explicit) == {ACTION}
    assert explicit[ACTION][0] == Decimal("0.0336129")
    with pytest.raises(ValueError, match="SESSION_OR_SUBJECT"):
        bind_cash_reference_terms(events, SUB, tuple(reversed(DAYS)), (terms,))
    with pytest.raises(ValueError, match="TERMS_SCOPE"):
        bind_cash_reference_terms(events, SUB, DAYS, (replace(terms, disclosed_date=DAYS[5]),))
