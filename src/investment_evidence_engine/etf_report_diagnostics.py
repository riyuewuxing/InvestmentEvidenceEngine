"""Exact arithmetic for explicitly supplied ETF report fields.

A disclosed NAV return, market price, share-unit movement and tracking
difference are distinct. This module never authenticates report publication,
constructs a total-return index, estimates expected alpha, or admits trades.
"""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, localcontext

HORIZONS = ("3M", "6M", "1Y")
REPORT_KEYS = {"symbol", "period_start", "period_end", "declared_report_day",
               "benchmark_label", "end_assets_cny", "end_nav_cny", "overview_end_units",
               "begin_units", "created_units", "redeemed_units", "split_units_label",
               "end_units", "realized_profit_cny", "profit_cny", "performance"}
PERFORMANCE_KEYS = {"nav_return_pct", "nav_std_pct", "benchmark_return_pct",
                    "benchmark_std_pct", "return_difference_pp", "std_difference_pp"}
BENCHMARK_LABELS = {"沪深300指数", "沪深300指数收益率"}
NAV_QUANTUM = Decimal("0.0001")
PP_QUANTUM = Decimal("0.01")


def _day(value: object) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("ETF_REPORT_DATE")
    return date.fromisoformat(value)


def _number(value: object, *, scale: int, signed: bool = False) -> Decimal:
    if not isinstance(value, str) or not re.fullmatch(
            (r"-?" if signed else "") + r"(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1," + str(scale) + r"})?", value):
        raise ValueError("ETF_REPORT_DECIMAL")
    return Decimal(value)


def _fmt(value: Decimal, quantum: Decimal) -> str:
    return format(value.quantize(quantum, rounding=ROUND_HALF_UP), "f")


def evaluate_report(fields: dict) -> dict:
    if not isinstance(fields, dict) or set(fields) != REPORT_KEYS:
        raise ValueError("ETF_REPORT_SCHEMA")
    symbol = fields["symbol"]
    if not isinstance(symbol, str) or not re.fullmatch(r"(?:51|52|56|58|159)[0-9]{3,4}", symbol) or len(symbol) != 6:
        raise ValueError("ETF_REPORT_SYMBOL")
    first, last, declared = (_day(fields[k]) for k in ("period_start", "period_end", "declared_report_day"))
    if (not 80 <= (last-first).days <= 92 or not last < declared
            or first.year != last.year or last.day != monthrange(last.year, last.month)[1]
            or first.day != 1 or (first.month, last.month) not in {(1, 3), (4, 6), (7, 9), (10, 12)}):
        raise ValueError("ETF_REPORT_QUARTER_SCOPE")
    if not isinstance(fields["benchmark_label"], str) or fields["benchmark_label"] not in BENCHMARK_LABELS:
        raise ValueError("ETF_REPORT_BENCHMARK_UNSUPPORTED")
    numbers = {key: _number(fields[key], scale=2) for key in
               ("overview_end_units", "begin_units", "created_units", "redeemed_units", "end_units",
                "end_assets_cny")}
    if any(numbers[k] <= 0 for k in ("overview_end_units", "begin_units", "end_units", "end_assets_cny")):
        raise ValueError("ETF_REPORT_NONPOSITIVE")
    nav = _number(fields["end_nav_cny"], scale=4)
    if nav <= NAV_QUANTUM/2 or not re.fullmatch(r"[0-9]+\.[0-9]{4}", fields["end_nav_cny"]):
        raise ValueError("ETF_REPORT_NAV_PRECISION")
    split_label = fields["split_units_label"]
    split = Decimal(0) if split_label == "DASH" else _number(split_label, scale=2, signed=True)
    if (numbers["overview_end_units"] != numbers["end_units"]
            or numbers["begin_units"]+numbers["created_units"]-numbers["redeemed_units"]+split != numbers["end_units"]):
        raise ValueError("ETF_REPORT_SHARE_ROLL_FORWARD")
    if not isinstance(fields["performance"], dict) or set(fields["performance"]) != set(HORIZONS):
        raise ValueError("ETF_REPORT_HORIZON_SCOPE")
    with localcontext() as ctx:
        ctx.prec = 64
        calculated_nav = numbers["end_assets_cny"]/numbers["end_units"]
        if calculated_nav.quantize(NAV_QUANTUM, rounding=ROUND_HALF_UP) != nav:
            raise ValueError("ETF_REPORT_NAV_ROUNDING_MISMATCH")
        net = numbers["created_units"]-numbers["redeemed_units"]
        realized = _number(fields["realized_profit_cny"], scale=2, signed=True)
        profit = _number(fields["profit_cny"], scale=2, signed=True)
        performance = {}
        for horizon in HORIZONS:
            row = fields["performance"][horizon]
            if not isinstance(row, dict) or set(row) != PERFORMANCE_KEYS:
                raise ValueError("ETF_REPORT_PERFORMANCE_SCHEMA")
            v = {k: _number(row[k], scale=2, signed=True) for k in PERFORMANCE_KEYS}
            if (min(v["nav_return_pct"], v["benchmark_return_pct"]) < -100
                    or min(v["nav_std_pct"], v["benchmark_std_pct"]) < 0):
                raise ValueError("ETF_REPORT_PERFORMANCE_DOMAIN")
            # Each printed cell is rounded independently to 0.01 pp.
            if (abs(v["nav_return_pct"]-v["benchmark_return_pct"]-v["return_difference_pp"]) > PP_QUANTUM
                    or abs(v["nav_std_pct"]-v["benchmark_std_pct"]-v["std_difference_pp"]) > PP_QUANTUM):
                raise ValueError("ETF_REPORT_PERFORMANCE_RECONCILIATION")
            performance[horizon] = {k: _fmt(value, PP_QUANTUM) for k, value in v.items()}
        return {"status": "WARN", "symbol": symbol, "period_start": first.isoformat(),
                "period_end": last.isoformat(), "declared_report_day": declared.isoformat(),
                "benchmark_label": fields["benchmark_label"],
                "benchmark_version_verified": False,
                "end_assets_cny": _fmt(numbers["end_assets_cny"], PP_QUANTUM),
                "reported_nav_cny": _fmt(nav, NAV_QUANTUM),
                "assets_over_units_nav_cny": _fmt(calculated_nav, Decimal("0.0000000001")),
                "nav_rounding_match": True,
                "end_units": format(numbers["end_units"], "f"),
                "net_creation_units": format(net, "f"),
                "net_creation_over_begin_pct": _fmt(100*net/numbers["begin_units"], Decimal("0.000001")),
                "split_units": format(split, "f"),
                "split_label_was_dash": split_label == "DASH",
                "share_roll_forward_match": True,
                "cash_flow_cny_verified": False,
                "realized_profit_cny": _fmt(realized, PP_QUANTUM),
                "accounting_profit_cny": _fmt(profit, PP_QUANTUM),
                "implied_fair_value_change_cny": _fmt(profit-realized, PP_QUANTUM),
                "performance": performance,
                "performance_basis": "ISSUER_REPORTED_NAV_RETURN_EXCLUDES_HOLDER_TRADING_FEES",
                "tracking_error_estimated": False, "holder_net_return_estimated": False,
                "historical_vintage_verified": False, "first_availability_verified": False,
                "formal_research_admitted": False, "decision_authority": False, "execution_allowed": False}


def compare_reports(left_fields: dict, right_fields: dict) -> dict:
    left, right = evaluate_report(left_fields), evaluate_report(right_fields)
    if left["symbol"] == right["symbol"]:
        raise ValueError("ETF_REPORT_SELF_COMPARISON")
    if any(left[k] != right[k] for k in ("period_start", "period_end")):
        raise ValueError("ETF_REPORT_PERIOD_MISMATCH")
    rows = {}
    with localcontext() as ctx:
        ctx.prec = 64
        for horizon in HORIZONS:
            a, b = left["performance"][horizon], right["performance"][horizon]
            if any(a[k] != b[k] for k in ("benchmark_return_pct", "benchmark_std_pct")):
                raise ValueError("ETF_REPORT_BENCHMARK_VALUES_CONFLICT")
            rows[horizon] = {
                "left_nav_return_pct": a["nav_return_pct"], "right_nav_return_pct": b["nav_return_pct"],
                "reported_benchmark_return_pct": a["benchmark_return_pct"],
                "left_minus_right_nav_return_pp": _fmt(Decimal(a["nav_return_pct"])-Decimal(b["nav_return_pct"]), PP_QUANTUM),
                "left_reported_tracking_difference_pp": a["return_difference_pp"],
                "right_reported_tracking_difference_pp": b["return_difference_pp"],
            }
    return {"status": "WARN", "left": left, "right": right, "paired_reported_horizons": rows,
            "reported_benchmark_numbers_match": True, "benchmark_version_verified": False,
            "inception_returns_compared": False, "tracking_error_estimated": False,
            "nav_level_used_as_rank": False, "cash_flow_cny_estimated": False,
            "expected_alpha_estimated": False, "formal_research_admitted": False,
            "decision_authority": False, "execution_allowed": False}


def closing_premium(fields: dict, *, symbol: str, session: str, raw_close: str) -> dict:
    """Conditional price/NAV ratio at the same historical session, not IOPV."""
    result = evaluate_report(fields)
    if symbol != result["symbol"] or session != result["period_end"]:
        raise ValueError("ETF_REPORT_PRICE_SCOPE")
    price = _number(raw_close, scale=4)
    if price <= 0:
        raise ValueError("ETF_REPORT_PRICE_NONPOSITIVE")
    nav = Decimal(result["reported_nav_cny"])
    with localcontext() as ctx:
        ctx.prec = 64
        center = (price/nav-1)*100
        low = (price/(nav+NAV_QUANTUM/2)-1)*100
        high = (price/(nav-NAV_QUANTUM/2)-1)*100
        return {"symbol": symbol, "session": session, "raw_close_cny": raw_close,
                "reported_nav_cny": result["reported_nav_cny"],
                "close_over_reported_nav_minus_one_pct": _fmt(center, Decimal("0.000001")),
                "nav_rounding_interval_pct": [format(low.quantize(Decimal("0.000001"), rounding=ROUND_FLOOR), "f"),
                                              format(high.quantize(Decimal("0.000001"), rounding=ROUND_CEILING), "f")],
                "ratio_basis": "RETROSPECTIVE_SAME_SESSION_CLOSE_OVER_REPORTED_NAV",
                "same_time_quote_and_nav_verified": False, "iopv_verified": False,
                "historical_public_availability_verified": False, "arbitrage_or_fill_inferred": False,
                "decision_authority": False}
