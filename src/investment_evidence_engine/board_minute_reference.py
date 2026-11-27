"""Validate a vendor-labelled board minute series, never grant historical PIT.

The proxy does not retain a verified publication/retrieval receipt for each bar.
Only close values are used: inferred OHLC extremes are not observed extrema.
"""
from datetime import datetime, time
from math import isfinite
from zoneinfo import ZoneInfo

SH = ZoneInfo("Asia/Shanghai")


def board_minute_reference(rows: list[dict], *, checked_at: datetime) -> dict:
    if checked_at.utcoffset() is None:
        raise ValueError("BOARD_CLOCK_UNKNOWN")
    local = checked_at.astimezone(SH)
    points = {}
    rejected = 0
    conflicting = False
    for row in rows:
        try:
            if not isinstance(row, dict):
                raise ValueError("row")
            stamp = datetime.strptime(row["time"], "%Y-%m-%d %H:%M").replace(tzinfo=SH)
            price = row["close"]
            if (stamp > local or stamp.strftime("%Y-%m-%d %H:%M") != row["time"]
                    or not (time(9, 30) <= stamp.time() <= time(11, 30)
                            or time(13) <= stamp.time() <= time(15))
                    or type(price) not in (int, float) or not isfinite(price) or price <= 0):
                raise ValueError("row")
            if stamp in points and points[stamp] != price:
                conflicting = True
            points[stamp] = price
        except (KeyError, ValueError, TypeError, OverflowError):
            rejected += 1
    if conflicting or not points:
        return {"status": "CONFLICTING_DUPLICATES" if conflicting else "UNAVAILABLE",
                "items": [], "rejected_count": rejected, "session_date": None,
                "formal_pit": False, "decision_authority": False}
    day = max(points).date()
    series = [{"time": stamp.strftime("%Y-%m-%d %H:%M"), "close": points[stamp]}
              for stamp in sorted(points) if stamp.date() == day]
    return {"status": "SAME_DATE_VENDOR_REFERENCE" if day == local.date() else "HISTORICAL_VENDOR_REFERENCE",
            "items": series, "rejected_count": rejected, "session_date": day.isoformat(),
            "formal_pit": False, "decision_authority": False}
