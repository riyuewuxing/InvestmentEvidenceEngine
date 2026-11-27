"""Bounded retrospective 5-minute CLOSE observation; not executable T prices."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from .cash_execution_math import canonical_cent
from .contracts import canonical_sha256
from .intraday_t_scenarios import FeeAssumptions, TAccountReference, TLeg, TScenario, compare_intraday_t

SH = ZoneInfo("Asia/Shanghai")


def expected_endpoints(session: date) -> tuple[str, ...]:
    times = []
    for start in ("09:30", "13:00"):
        begin = datetime.fromisoformat(f"{session.isoformat()}T{start}:00+08:00")
        times.extend((begin + timedelta(minutes=5*i)).strftime("%H:%M") for i in range(1, 25))
    return tuple(times)


def normalized_closes(rows: list, *, session: date, source: str, symbol: str) -> dict:
    """Require exactly one observed close at each completed regular 5m endpoint."""
    if source not in {"baostock", "sina"} or symbol != "000001" or type(session) is not date:
        raise ValueError("INTRADAY_REFERENCE_SCOPE")
    if not isinstance(rows, list) or len(rows) > 200:
        raise ValueError("INTRADAY_ROW_BOUND")
    found = {}
    expected = expected_endpoints(session)
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("INTRADAY_ROW_SCHEMA")
        raw_time = row["time"]
        stamp = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S")
        if stamp.strftime("%Y-%m-%d %H:%M:%S") != raw_time:
            raise ValueError("INTRADAY_TIME_SCHEMA")
        if source == "baostock" and (row.get("code") != "sz.000001" or row.get("adjustflag") != "3"):
            raise ValueError("INTRADAY_CODE_OR_ADJUSTMENT")
        if stamp.date() != session:
            if source == "sina" and stamp.date() < session:
                continue
            raise ValueError("INTRADAY_SESSION_MISMATCH")
        minute = stamp.strftime("%H:%M")
        if stamp.second or minute not in expected or minute in found:
            raise ValueError("INTRADAY_DUPLICATE_OR_UNEXPECTED_ENDPOINT")
        try:
            o, h, lo, c = [canonical_cent(Decimal(str(row[k]))) for k in ("open", "high", "low", "close")]
            vol = Decimal(str(row["volume"]))
            if not vol.is_finite() or vol < 0 or vol != vol.to_integral_value() or not lo <= min(o, c) <= max(o, c) <= h:
                raise ValueError("INTRADAY_BAR_SCOPE")
        except (ArithmeticError, TypeError, ValueError, KeyError):
            raise ValueError("INTRADAY_BAR_SCOPE") from None
        found[minute] = {"open": str(o), "high": str(h), "low": str(lo), "close": str(c), "volume": str(vol)}
    complete = set(found) == set(expected)
    return {"source": source, "session": session.isoformat(), "count": len(found), "complete": complete,
            "bars": found, "normalized_sha256": canonical_sha256(found),
            "missing_count": len(set(expected)-set(found))}


def retrospective_t_close_sensitivity(primary: dict, secondary: dict | None, daily: dict, *,
                                       session: date, evaluated_at: datetime) -> dict:
    """Fixed 10:00/14:30 closes; zero-spread hypothetical fee sensitivity only."""
    if evaluated_at.utcoffset() is None or evaluated_at.astimezone(SH) < datetime.fromisoformat(
            f"{session.isoformat()}T15:30:00+08:00"):
        raise ValueError("INTRADAY_SESSION_NOT_COMPLETE")
    result = {"status": "BLOCK", "subject_id": "000001", "session_date": session.isoformat(),
              "evaluated_at": evaluated_at.isoformat(), "fixed_endpoints": ["10:00", "14:30", "15:00"],
              "historical_vintage_verified": False, "independent_upstream_verified": False,
              "actual_fills_verified": False, "bid_ask_observed": False,
              "broker_fee_verified": False, "decision_authority": False,
              "execution_allowed": False, "research_only": True}
    if (primary.get("source") != "baostock" or primary.get("session") != session.isoformat()
            or primary.get("complete") is not True or set(primary.get("bars", {})) != set(expected_endpoints(session))
            or primary.get("normalized_sha256") != canonical_sha256(primary["bars"])):
        return result | {"reason": "PRIMARY_COMPLETE_SESSION_REQUIRED"}
    b = primary["bars"]
    if (daily.get("code") != "sz.000001" or daily.get("date") != session.isoformat()
            or daily.get("adjustflag") != "3" or daily.get("tradestatus") != "1"
            or daily.get("isST") != "0" or daily.get("calendar_open") is not True):
        return result | {"reason": "DAILY_STATE_OR_CALENDAR_UNAVAILABLE"}
    try:
        pre = canonical_cent(Decimal(daily["preclose"]))
        daily_close = canonical_cent(Decimal(daily["close"]))
        high = canonical_cent(Decimal(daily["high"]))
        low = canonical_cent(Decimal(daily["low"]))
        op = canonical_cent(Decimal(daily["open"]))
        if (daily_close != Decimal(b["15:00"]["close"])
                or op != Decimal(b["09:35"]["open"])
                or high != max(Decimal(x["high"]) for x in b.values())
                or low != min(Decimal(x["low"]) for x in b.values())):
            return result | {"reason": "MINUTE_DAILY_OHLC_CONFLICT"}
    except (KeyError, ArithmeticError, ValueError, TypeError):
        return result | {"reason": "DAILY_OHLC_INVALID"}
    match = "UNAVAILABLE"
    if secondary is not None:
        if (secondary.get("source") != "sina" or secondary.get("session") != session.isoformat()
                or secondary.get("complete") is not True
                or set(secondary.get("bars", {})) != set(expected_endpoints(session))
                or secondary.get("normalized_sha256") != canonical_sha256(secondary["bars"])):
            match = "INCOMPLETE"
        else:
            match = "MATCH" if all(Decimal(b[t]["close"]) == Decimal(secondary["bars"][t]["close"])
                                   for t in b) else "CONFLICT"
    if match == "CONFLICT":
        return result | {"reason": "MINUTE_SOURCE_CLOSE_CONFLICT", "close_crosscheck": match}
    # Use a synthetic envelope independent of any real account. Both side
    # prices equal a bar's last price; this assumes zero spread and is NOT a fill.
    first, second = (b[t]["close"] for t in ("10:00", "14:30"))
    def leg(minute, price):
        return TLeg(at=f"{session.isoformat()}T{minute}:00+08:00",
                    buy_price_cny=price, sell_price_cny=price,
                    buy_fill="ASSUME_FILLED", sell_fill="ASSUME_FILLED", market_state="ASSUMED_OPEN")
    scenario = TScenario(session_date=session.isoformat(), calendar_state="ASSUMED_TRADING_DAY",
        reference_close_cny=str(pre), limit_rate="0.10", minimum_buy_units=100,
        buy_increment=100, quantity=100, first=leg("10:00", first), second=leg("14:30", second),
        terminal_mark_cny=str(daily_close), terminal_mark_at=f"{session.isoformat()}T15:00:00+08:00",
        fees=FeeAssumptions(commission_rate="0.0003", minimum_commission_cny="5",
                           transfer_rate="0.00001", sell_stamp_rate="0.0005"))
    try:
        out = compare_intraday_t(TAccountReference(cash_cny="10000", held_units=100, sellable_old_units=100), scenario)
    except ValueError:
        return result | {"reason": "ASSUMED_BAND_OR_PRICE_INVALID"}
    return result | {
        "status": "RETROSPECTIVE_CLOSE_SENSITIVITY_ONLY",
        "reason": "ZERO_SPREAD_ASSUMED_BAR_CLOSES_NOT_QUOTES_OR_FILL",
        "close_crosscheck": match,
        "observed_primary_count": primary["count"],
        "observed_secondary_count": secondary["count"] if secondary else 0,
        "primary_normalized_sha256": primary["normalized_sha256"],
        "secondary_normalized_sha256": secondary["normalized_sha256"] if secondary else None,
        "daily_ohlc_match": True,
        "daily_state_provider": "baostock_same_provider_not_independent",
        "close_change_10_to_1430_pct": float((Decimal(second)/Decimal(first)-1)*100),
        "assumptions": {"synthetic_initial_cash_cny": "10000", "synthetic_old_units": 100,
                        "quantity": 100, "spread_assumed_zero": True, "limit_rate_assumed": "0.10",
                        "fee_scenario": scenario.fees.model_dump()},
        "conditional_results": {key: {field: out[key].get(field) for field in (
            "status", "reason", "matched_net_cash_delta_cny", "delta_vs_no_action_cny", "position_delta_units")}
            for key in ("positive_t", "reverse_t")},
    }
