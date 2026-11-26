from datetime import UTC, date, datetime, timedelta

import pytest

from investment_evidence_engine.historical_reference import DailyClose, HistoricalCloseSeries
from investment_evidence_engine.holding_risk import (
    CashDistribution,
    CashDistributionInputs,
    holding_period_reference,
)
from investment_evidence_engine.market_calendar import (
    CalendarObservation,
    check_calendar,
    scheduled_days,
)

START = date(2025,11,25)
END = date(2026,11,25)
NOW = datetime(2026,11,26,5,tzinfo=UTC)
CAL = CalendarObservation(first_requested=START,last_requested=END,observed_at=NOW,
                          rows=scheduled_days(START,END))
DATES = tuple(row.day for row in CAL.rows if row.is_trading_day)


def series(symbol, prices, dates=DATES):
    return HistoricalCloseSeries(subject_id=symbol,currency="CNY",price_basis="RAW_CLOSE",
        source_label="synthetic", closes=tuple(DailyClose(session=d,close=float(p)) for d,p in zip(dates,prices)))


def test_verified_calendar_closures_and_holiday_weekends():
    sessions=check_calendar(CAL,first=START,last=END,cutoff=NOW)
    assert date(2026,1,2) not in sessions
    assert date(2026,2,23) not in sessions
    assert date(2026,2,24) in sessions
    assert date(2026,9,25) not in sessions
    assert date(2026,10,7) not in sessions
    assert date(2026,10,8) in sessions
    assert date(2026,10,10) not in sessions
    assert sessions[-1]==END


@pytest.mark.parametrize("fault",["missing","duplicate","wrong_flag","wrong_scope","future","unsupported"])
def test_calendar_faults(fault):
    cal=CAL
    first,last=START,END
    with pytest.raises(ValueError):
        if fault=="missing":
            cal=cal.model_copy(update={"rows":cal.rows[:10]+cal.rows[11:]})
        elif fault=="duplicate":
            cal=cal.model_copy(update={"rows":cal.rows[:10]+(cal.rows[9],)+cal.rows[10:]})
        elif fault=="wrong_flag":
            cal=cal.model_copy(update={"rows":(cal.rows[0].model_copy(update={"is_trading_day":False}),)+cal.rows[1:]})
        elif fault=="wrong_scope":
            first+=timedelta(days=1)
        elif fault=="future":
            cal=cal.model_copy(update={"observed_at":NOW+timedelta(seconds=1)})
        else:
            scheduled_days(date(2024,1,1),date(2025,1,1))
        check_calendar(cal,first=first,last=last,cutoff=NOW)


def test_common_missing_session_not_silently_intersected():
    prices=[100]*len(DATES)
    with pytest.raises(ValueError,match="PRICE_SESSION_COVERAGE_INCOMPLETE"):
        holding_period_reference(series("600000",prices,DATES[1:]),series("510300",prices,DATES[1:]),
            CAL,first=START,last=END,cutoff=NOW)


def test_cash_ex_date_reinvestment_distinguishes_price_drop_from_cash_return():
    i=10
    prices=[100]*i+[90]*(len(DATES)-i)
    a=series("600000",prices); b=series("510300",[100]*len(DATES))
    event=CashDistribution(subject_id="600000",disclosed_date=DATES[i-1],ex_date=DATES[i],
        gross_cash_per_unit_cny=10.,source_locator="https://example.invalid/disclosure")
    future=event.model_copy(update={"ex_date":date(2026,12,1)})
    result=holding_period_reference(a,b,CAL,first=START,last=END,cutoff=NOW,
        distributions=CashDistributionInputs(events=(event,future)))
    assert result["raw_full_window_pct"]["candidate"]==pytest.approx(-10)
    assert result["cash_full_window_pct"]["candidate"]==pytest.approx(0)
    assert len(result["cash_scenario_event_audit"]["included"])==1
    assert result["cash_scenario_event_audit"]["excluded"][0]["reason"]=="AFTER_CUTOFF"
    assert result["raw_price_windows"][2]["holding_sessions"]==20
    assert result["raw_price_windows"][2]["rolling_windows"]==len(DATES)-20
    assert result["raw_price_windows"][2]["disjoint_windows_upper_bound"]==(len(DATES)-1)//20
    assert not result["corporate_action_coverage_verified"] and not result["decision_authority"]
    assert not result["forward_probability_estimated"]


def test_horizon_reference_uses_direct_compound_returns():
    a=series("600000",[100*1.01**i for i in range(len(DATES))])
    b=series("510300",[100]*len(DATES))
    result=holding_period_reference(a,b,CAL,first=START,last=END,cutoff=NOW)
    for row in result["raw_price_windows"]:
        assert row["status"]=="DESCRIPTIVE_ONLY"
        assert row["candidate"]["median_pct"]==pytest.approx((1.01**row["holding_sessions"]-1)*100)
        assert row["candidate"]["observed_loss_frequency_pct"]==0
        assert not row["independent_trials_verified"]
    assert result["cash_scenario_status"]=="NOT_SUPPLIED"
