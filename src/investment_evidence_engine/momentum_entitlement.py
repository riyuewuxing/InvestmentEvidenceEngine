"""Conditional gross cash-entitlement sensitivity on the existing fixed profile.

The price-only signal, split, fee assumptions and exposure path are unchanged.
A separate nominal gross entitlement sleeve is marked but never spendable,
reinvested, taxed, or declared paid. This is not a total-return certification,
a point-in-time replay, an account ledger or an executable strategy.
"""
from __future__ import annotations

import math
from datetime import date
from decimal import Decimal

from .action_reference import bind_cash_reference_terms
from .cash_entitlement import CashEntitlementTerms
from .historical_capture import PublicSecurity
from .holding_risk import CashDistributionInputs
from .market_calendar import scheduled_days
from .momentum_profile import WINDOW, momentum_metrics, momentum_profile


def segregated_entitlement_metrics(opens: list[float], targets: list[int], bps: int,
                                   events: dict[int, Decimal]) -> dict:
    """An event at opening i belongs to exposure on interval i-1 -> i.

    Fresh segment starts flat. An ex-opening purchase gets nothing, a sale
    at that opening retains the prior record-close entitlement. An event
    on the terminal open is included if the preceding interval was held.
    The cash sleeve is not invested again; no fee is charged on the sleeve.
    """
    if (not isinstance(opens, list) or not isinstance(targets, list)
            or len(opens) != len(targets)+1
            or any(type(v) not in {int, float} or not math.isfinite(v) or v <= 0 for v in opens)
            or not isinstance(events, dict) or len(events) > 100
            or any(type(i) is not int or not 0 <= i < len(opens)
                   or type(v) is not Decimal or not v.is_finite() or not 0 < v <= Decimal("1000000")
                   for i, v in events.items())):
        raise ValueError("ENTITLEMENT_PROFILE_INPUT")
    gross = [b/a for a, b in zip(opens[:-1], opens[1:], strict=True)]
    base = momentum_metrics(gross, targets, bps)
    wealth, marked_peak, drawdown, accrued = 1.0, 1.0, 0.0, 0.0
    old = 0
    cost = bps/10000
    audit = []
    if 0 in events:
        audit.append({"open_index": 0, "held_at_previous_record_close": False,
                      "gross_cash_per_share_cny": str(events[0]), "gross_entitlement_per_initial_cny": 0.0})
    for i, (ratio, target) in enumerate(zip(gross, targets, strict=True)):
        wealth *= 1 - cost * abs(target-old)
        marked = wealth + accrued
        drawdown = max(drawdown, 1 - marked/marked_peak)
        units = wealth/opens[i] if target else 0.0
        wealth *= 1 + target*(ratio-1)
        # Mark the ex-day entitlement before any next-open transition,
        # including terminal liquidation. It remains segregated forever.
        if i+1 in events:
            credit = units*float(events[i+1])
            accrued += credit
            audit.append({"open_index": i+1, "held_at_previous_record_close": bool(target),
                          "gross_cash_per_share_cny": str(events[i+1]),
                          "gross_entitlement_per_initial_cny": credit})
        marked = wealth + accrued
        if not math.isfinite(marked) or wealth <= 0:
            raise ValueError("ENTITLEMENT_PROFILE_WEALTH")
        marked_peak = max(marked_peak, marked)
        drawdown = max(drawdown, 1-marked/marked_peak)
        old = target
    wealth *= 1-cost*old
    marked = wealth+accrued
    drawdown = max(drawdown, 1-marked/marked_peak)
    if not math.isfinite(marked) or not math.isfinite(accrued) or wealth <= 0:
        raise ValueError("ENTITLEMENT_PROFILE_WEALTH")
    # Keep the original engine's exact arithmetic/order and receipt unchanged.
    if not math.isclose((wealth-1)*100, base["net_price_change_pct"], abs_tol=1e-10, rel_tol=1e-12):
        raise ValueError("ENTITLEMENT_PRICE_BASELINE_MISMATCH")
    return {"price_only": base, "price_plus_nominal_gross_entitlement_change_pct": (marked-1)*100,
            "gross_entitlement_increment_pp": accrued*100,
            "max_conditional_marked_open_drawdown_pct": drawdown*100,
            "events": audit, "gross_entitlement_reinvested": False,
            "actual_payment_verified": False, "actual_costs_verified": False,
            "complete_corporate_action_history_verified": False, "decision_authority": False}


def momentum_entitlement_profile(dates: tuple[date, ...], closes: list[float], opens: list[float],
                                 *, subject: PublicSecurity, events: CashDistributionInputs,
                                 reference_terms: tuple[CashEntitlementTerms, ...]) -> dict:
    baseline = momentum_profile(dates, closes, opens)
    if dates != tuple(r.day for r in scheduled_days(dates[0], dates[-1]) if r.is_trading_day):
        raise ValueError("ENTITLEMENT_PROFILE_CALENDAR_COVERAGE")
    included, excluded, explicit = bind_cash_reference_terms(events, subject, dates, reference_terms)
    if set(included) != set(explicit):
        raise ValueError("ENTITLEMENT_PROFILE_EXPLICIT_TERMS_REQUIRED")
    terms = {t.ex_date: t for t in reference_terms}
    index = {d.isoformat(): i for i, d in enumerate(dates)}
    segments = []
    in_segments = set()
    for old in baseline["segments"]:
        first = index[old["first_entry_open"]]
        terminal = index[old["terminal_open"]]
        window = opens[first:terminal+1]
        target = [int(closes[t-1] > closes[t-1-WINDOW]) for t in range(first, terminal)]
        local_events = {index[d.isoformat()]-first: t.gross_per_share for d, t in terms.items()
                        if first <= index[d.isoformat()] <= terminal}
        in_segments.update(dates[first+i] for i in local_events)
        stress = []
        for case in old["stress"]:
            row = {"one_way_bps": case["one_way_bps"]}
            for name, exposure in (("signal_rule", target), ("constant_invested", [1]*len(target)),
                                   ("flat_cash_assumed_zero_interest", [0]*len(target))):
                result = segregated_entitlement_metrics(window, exposure, case["one_way_bps"], local_events)
                if result["price_only"] != case[name]:
                    raise ValueError("ENTITLEMENT_PROFILE_BASELINE_MISMATCH")
                for item in result["events"]:
                    ex = dates[first+item.pop("open_index")]
                    item["ex_date"] = ex.isoformat()
                    item["record_date"] = terms[ex].record_date.isoformat()
                    item["source_locator"] = terms[ex].source_locator
                row[name] = result
            stress.append(row)
        segments.append({"segment": old["segment"], "first_entry_open": old["first_entry_open"],
                         "terminal_open": old["terminal_open"], "intervals": old["intervals"],
                         "stress": stress})
    return {"status": "CONDITIONAL_SEGREGATED_GROSS_ENTITLEMENT_SENSITIVITY",
            "subject": subject.symbol, "observations": len(dates),
            "price_only_baseline": baseline, "segments": segments,
            "explicit_terms": [t.checked() for t in reference_terms],
            "explicit_events_excluded_by_input_window": excluded,
            "included_events_outside_independent_segments": [d.isoformat() for d in sorted(set(terms)-in_segments)],
            "signal_price_basis": "UNCHANGED_RAW_CLOSE_PRICE_ONLY",
            "cash_convention": "PRIOR_RECORD_CLOSE_HOLDING_NOMINAL_GROSS_SEPARATE_NOT_SPENDABLE",
            "first_segment_starts_flat": True, "each_segment_starts_flat": True,
            "actual_cash_payment_verified": False, "shareholder_tax_verified": False,
            "actual_trade_feasibility_verified": False, "actual_costs_verified": False,
            "complete_corporate_action_history_verified": False, "historical_vintage_verified": False,
            "total_return_certified": False, "model_selection_performed": False,
            "decision_authority": False, "execution_allowed": False, "pit_safe": False}
