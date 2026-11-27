from investment_evidence_engine.historical_capture import PublicSecurity, _from_rows
from investment_evidence_engine.market_calendar import scheduled_days
from investment_evidence_engine.public_current_research_price import FIRST, LAST, summarize_supplement


def test_supplement_different_projection_cannot_claim_match():
    days = tuple(d.day for d in scheduled_days(FIRST, LAST) if d.is_trading_day)
    series = _from_rows([[d.isoformat(), 4.0] for d in days],
                       PublicSecurity(symbol="510300", asset_type="ETF"), "eastmoney", FIRST, LAST)
    result = summarize_supplement(series, days)
    assert result["status"] == "BLOCK"
    assert result["observed_calendar_sessions_match"]
    assert not result["exact_prior_tencent_projection_match"]
