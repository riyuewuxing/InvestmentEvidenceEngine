from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from investment_evidence_engine.us_core_session import us_equity_core_close_minutes


@pytest.mark.parametrize("day", [
    date(2026, 11, 27), date(2026, 12, 24), date(2027, 11, 26),
])
def test_reviewed_early_close_dates(day):
    assert us_equity_core_close_minutes(day) == 780


@pytest.mark.parametrize("day", [
    date(2026, 7, 2), date(2026, 11, 25), date(2027, 7, 2),
])
def test_no_unpublished_early_close_inference(day):
    assert us_equity_core_close_minutes(day) == 960


def test_thanksgiving_friday_boundary_in_eastern_time():
    tz = ZoneInfo("America/New_York")
    before = datetime(2026, 11, 27, 17, 59, 59, tzinfo=UTC).astimezone(tz)
    close = datetime(2026, 11, 27, 18, 0, tzinfo=UTC).astimezone(tz)
    assert before.hour * 60 + before.minute < us_equity_core_close_minutes(before.date())
    assert close.hour * 60 + close.minute == us_equity_core_close_minutes(close.date())
    with pytest.raises(TypeError):
        us_equity_core_close_minutes(close)
