"""Reviewed NYSE core-equity early-close overrides (2026–2027).

Reference: https://www.nyse.com/trade/hours-calendars
Reviewed 2026-11-26. Nasdaq's 2026 holiday calendar independently lists
the same November 27 and December 24 early closes. This is a scheduled
core-session reference, not a live status, options or extended-hours feed.
Full-day holiday checks remain the caller's responsibility.
"""
from datetime import date

US_EQUITY_EARLY_CLOSE_DATES = frozenset({
    date(2026, 11, 27),
    date(2026, 12, 24),
    date(2027, 11, 26),
})


def us_equity_core_close_minutes(local_day: date) -> int:
    """Return scheduled ET close minutes; only reviewed dates override 16:00.

    The normal-hours default is not proof of a trading day, emergency
    closure coverage or reviewed schedules outside the stated years.
    """
    if type(local_day) is not date:
        raise TypeError("US_CORE_CLOSE_REQUIRES_LOCAL_DATE")
    return 13 * 60 if local_day in US_EQUITY_EARLY_CLOSE_DATES else 16 * 60
