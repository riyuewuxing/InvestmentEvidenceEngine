from datetime import UTC, date, datetime

import pytest

from investment_evidence_engine.historical_reference import DailyClose, HistoricalCloseSeries
from investment_evidence_engine.market_calendar import CalendarObservation, scheduled_days
from investment_evidence_engine.portfolio_stress import (
    PortfolioStressInputs,
    StressPosition,
    historical_cash_substitution_stress,
)

FIRST=date(2025,11,25)
LAST=date(2026,11,25)
NOW=datetime(2026,11,26,5,tzinfo=UTC)
CAL=CalendarObservation(first_requested=FIRST,last_requested=LAST,observed_at=NOW,
                        rows=scheduled_days(FIRST,LAST))
DAYS=tuple(row.day for row in CAL.rows if row.is_trading_day)


def prices(symbol,rate,days=DAYS):
    return HistoricalCloseSeries(subject_id=symbol,currency="CNY",price_basis="RAW_CLOSE",
        source_label="synthetic",closes=tuple(DailyClose(session=d,close=100.*rate**i)
                                             for i,d in enumerate(days)))


def inputs():
    return PortfolioStressInputs(initial_equity_cny=100.,cash_cny=40.,notional_cny=20.,
        positions=(StressPosition(subject_id="600000",market_value_cny=60.),),
        candidate_id="600000",alternative_id="510300")


def stress(i,series,calendar=CAL):
    return historical_cash_substitution_stress(i,series,calendar,first=FIRST,last=LAST,cutoff=NOW)


def test_cash_substitution_direct_window_math_existing_candidate_position():
    result=stress(inputs(),(prices("600000",.99),prices("510300",1.01)))
    one=result["windows"][0]
    assert one["baseline"]["median_pct"]==pytest.approx(-.6)
    assert one["candidate"]["tail_loss_pct"]==pytest.approx(.8)
    assert one["alternative"]["tail_loss_pct"]==pytest.approx(.4)
    assert one["candidate_minus_baseline_tail_loss_pp"]==pytest.approx(.2)
    assert one["alternative_minus_baseline_tail_loss_pp"]==pytest.approx(-.2)
    assert one["candidate_minus_alternative_tail_loss_pp"]==pytest.approx(.4)
    twenty=result["windows"][-1]
    assert twenty["baseline"]["median_pct"]==pytest.approx(60*(.99**20-1))
    assert not twenty["independent_trials_verified"]
    assert not result["decision_authority"] and not result["formal_marginal_portfolio_risk_estimated"]


def test_all_cash_baseline_no_risk_free_claim():
    i=inputs().model_copy(update={"positions":(),"cash_cny":100.})
    result=stress(i,(prices("600000",.99),prices("510300",1.01)))
    assert result["windows"][0]["baseline"]["tail_loss_pct"]==0
    assert "NOT_RISK_FREE" in result["cash_policy"]


@pytest.mark.parametrize("fault",["missing","extra","duplicate","basis","cash","equity","calendar","identity"])
def test_fail_closed_inputs(fault):
    i=inputs()
    a,b=prices("600000",.99),prices("510300",1.01)
    series=(a,b)
    calendar=CAL
    if fault=="missing":
        series=(a,)
    elif fault=="extra":
        series=(a,b,prices("000001",1.))
    elif fault=="duplicate":
        series=(a,b,b)
    elif fault=="basis":
        series=(a,b.model_copy(update={"price_basis":"PROVIDER_ADJUSTED_CLOSE_NOT_VINTAGE_VERIFIED"}))
    elif fault=="cash":
        i=i.model_copy(update={"notional_cny":41.})
    elif fault=="equity":
        i=i.model_copy(update={"initial_equity_cny":101.})
    elif fault=="calendar":
        series=(a,prices("510300",1.01,DAYS[1:]))
    elif fault=="identity":
        i=i.model_copy(update={"candidate_id":"510300"})
    with pytest.raises(ValueError):
        stress(i,series,calendar)


def test_tail_is_not_same_as_difference_of_individual_security_losses():
    # The same window contains both holdings; a perfectly opposite path can
    # offset baseline losses, unlike subtracting unpaired independent tails.
    a=HistoricalCloseSeries(subject_id="600000",currency="CNY",price_basis="RAW_CLOSE",
        source_label="synthetic",closes=tuple(DailyClose(session=d,close=100.+10*(i%2)) for i,d in enumerate(DAYS)))
    b=HistoricalCloseSeries(subject_id="510300",currency="CNY",price_basis="RAW_CLOSE",
        source_label="synthetic",closes=tuple(DailyClose(session=d,close=110.-10*(i%2)) for i,d in enumerate(DAYS)))
    i=PortfolioStressInputs(initial_equity_cny=100.,cash_cny=50.,notional_cny=50.,
        positions=(StressPosition(subject_id="600000",market_value_cny=50.),),
        candidate_id="600000",alternative_id="510300")
    result=stress(i,(a,b))["windows"][0]
    assert result["alternative"]["tail_loss_pct"]==0
    assert result["candidate_minus_baseline_tail_loss_pp"]>0
