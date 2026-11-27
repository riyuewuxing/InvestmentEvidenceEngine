"""Conditional cash execution arithmetic, not a market fill or PIT witness.

All amounts use explicit Decimal inputs. Commission includes regulatory
charges; transfer and stamp are separate assumptions. No broker terms,
market impact, queue capacity, historical rate coverage or order is inferred.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import NamedTuple

TICK = Decimal("0.01")


def _finite(value: Decimal, *, maximum: Decimal, positive: bool = False) -> Decimal:
    if (type(value) is not Decimal or not value.is_finite() or not 0 <= value <= maximum
            or (positive and value == 0)):
        raise ValueError("CASH_EXECUTION_NUMERIC_SCOPE")
    return value


def price_band(reference: Decimal, rate: Decimal, *, exact_cent: bool = True) -> tuple[Decimal, Decimal]:
    """Conditional one-cent stock price band; enforce minimum one-tick movement.

    exact_cent=False is only for legacy synthetic/unspecified-price scenarios.
    The caller must establish rule applicability, reference source, and dates.
    """
    _finite(reference, maximum=Decimal("1000000"), positive=True)
    _finite(rate, maximum=Decimal("0.99999999"), positive=True)
    if type(exact_cent) is not bool:
        raise ValueError("CASH_EXECUTION_PRECISION_FLAG")
    with localcontext() as ctx:
        ctx.prec = 48
        rounded = reference.quantize(TICK, rounding=ROUND_HALF_UP)
        if reference < TICK or (exact_cent and rounded != reference):
            raise ValueError("CASH_EXECUTION_REFERENCE_NOT_CENT")
        # The ordinary formula is evaluated from the supplied reference. The
        # one-tick floor is tied to the rounded quotation tick.
        upper = (reference * (1 + rate)).quantize(TICK, rounding=ROUND_HALF_UP)
        lower = (reference * (1 - rate)).quantize(TICK, rounding=ROUND_HALF_UP)
        return max(TICK, min(lower, rounded - TICK)), max(upper, rounded + TICK)


class OrderFees(NamedTuple):
    commission: Decimal
    transfer: Decimal
    stamp: Decimal

    @property
    def total(self) -> Decimal:
        with localcontext() as ctx:
            ctx.prec = 48
            return self.commission + self.transfer + self.stamp


def order_fees(notional: Decimal, *, side: str, commission_rate: Decimal,
               minimum_commission: Decimal, transfer_rate: Decimal,
               sell_stamp_rate: Decimal) -> OrderFees:
    """Explicit per-order half-up scenario. Rates are fractions, not bps."""
    _finite(notional, maximum=Decimal("1e15"), positive=True)
    _finite(minimum_commission, maximum=Decimal("1e12"))
    for value in (commission_rate, transfer_rate, sell_stamp_rate):
        _finite(value, maximum=Decimal("0.99999999"))
    if side not in ("BUY", "SELL"):
        raise ValueError("CASH_EXECUTION_SIDE")
    with localcontext() as ctx:
        ctx.prec = 48
        if notional != notional.quantize(TICK):
            raise ValueError("CASH_EXECUTION_NOTIONAL_NOT_CENT")
        return OrderFees(
            max(notional * commission_rate, minimum_commission).quantize(TICK, rounding=ROUND_HALF_UP),
            (notional * transfer_rate).quantize(TICK, rounding=ROUND_HALF_UP),
            (notional * sell_stamp_rate if side == "SELL" else Decimal(0)).quantize(
                TICK, rounding=ROUND_HALF_UP),
        )


def affordable_units(cash: Decimal, price: Decimal, *, minimum_units: int, increment: int,
                     commission_rate: Decimal, minimum_commission: Decimal,
                     transfer_rate: Decimal) -> int:
    """Find the largest affordable permitted lot with exact rounded fees.

    Binary search keeps the work logarithmic; zero is always affordable.
    """
    _finite(cash, maximum=Decimal("1e15"))
    _finite(price, maximum=Decimal("1000000"), positive=True)
    if (type(minimum_units) is not int or type(increment) is not int
            or not 1 <= minimum_units <= 1000000 or not 1 <= increment <= 1000000):
        raise ValueError("CASH_EXECUTION_LOT_SCOPE")
    with localcontext() as ctx:
        ctx.prec = 48
        if cash != cash.quantize(TICK) or price != price.quantize(TICK) or price < TICK:
            raise ValueError("CASH_EXECUTION_CASH_OR_PRICE_NOT_CENT")
        args = dict(side="BUY", commission_rate=commission_rate, minimum_commission=minimum_commission,
                    transfer_rate=transfer_rate, sell_stamp_rate=Decimal(0))
        order_fees(TICK, **args)
        upper = int(cash // price)
        if upper < minimum_units:
            return 0
        lo, hi = 0, (upper - minimum_units) // increment
        result = 0
        while lo <= hi:
            mid = (lo + hi) // 2
            qty = minimum_units + mid * increment
            notional = qty * price
            if notional + order_fees(notional, **args).total <= cash:
                result = qty
                lo = mid + 1
            else:
                hi = mid - 1
        return result


def canonical_cent(value: Decimal) -> Decimal:
    """Normalize tiny binary-float transport residue, not a sub-cent quote."""
    _finite(value, maximum=Decimal("1000000"), positive=True)
    with localcontext() as ctx:
        ctx.prec = 48
        rounded = value.quantize(TICK, rounding=ROUND_HALF_UP)
        if rounded < TICK or abs(value - rounded) > Decimal("0.000000001"):
            raise ValueError("CASH_EXECUTION_REFERENCE_NOT_CENT")
        return rounded


class ReferenceDay(NamedTuple):
    session: date
    close: Decimal
    previous_reference: Decimal | None
    suspended: bool | None
    volume: Decimal | None


def reference_chain(rows: tuple[ReferenceDay, ...], *,
                    preceding_close: Decimal | None = None) -> dict:
    """Strict cash-price diagnostic: refuse missing references/action breaks.

    A reported suspension is not a trade. Missing suspended volume stays
    missing; a suspended close must reconcile to the last observed close.
    The first reported reference is not an independent historical witness.
    No complete corporate-action, calendar, source-vintage or fill claim.
    """
    if (not isinstance(rows, tuple) or not 1 <= len(rows) <= 10000
            or any(type(row) is not ReferenceDay or type(row.session) is not date for row in rows)):
        raise ValueError("CASH_EXECUTION_REFERENCE_ROW_SCOPE")
    dates = tuple(row.session for row in rows)
    if dates != tuple(sorted(set(dates))):
        raise ValueError("CASH_EXECUTION_REFERENCE_DATE_ORDER")
    previous = None if preceding_close is None else canonical_cent(preceding_close)
    blockers = []
    first_unanchored = False
    for row in rows:
        def block(reason: str) -> None:
            blockers.append({"session": row.session.isoformat(), "reason": reason})

        try:
            close = canonical_cent(row.close)
            ref = None if row.previous_reference is None else canonical_cent(row.previous_reference)
        except ValueError:
            block("INVALID_LIMIT_REFERENCE_OR_CLOSE")
            previous = None
            continue
        if type(row.suspended) is not bool:
            block("POINT_IN_TIME_SUSPENSION_STATUS_MISSING")
            previous = None
            continue
        if row.volume is not None:
            try:
                _finite(row.volume, maximum=Decimal("1e15"))
            except ValueError:
                block("INVALID_DAILY_VOLUME")
                previous = None
                continue
            if row.volume != row.volume.to_integral_value():
                block("INVALID_DAILY_VOLUME")
                previous = None
                continue
        if row.suspended:
            if row.volume not in (None, Decimal(0)):
                block("SUSPENSION_VOLUME_CONFLICT")
            if previous is None or close != previous:
                block("SUSPENDED_CLOSE_NOT_RECONCILED")
            if ref is not None and previous is not None and ref != previous:
                block("CORPORATE_ACTION_OR_REFERENCE_DISCONTINUITY")
            continue
        if row.volume is None or row.volume <= 0:
            block("TRADE_VOLUME_MISSING_OR_NONPOSITIVE")
        if ref is None:
            block("EXPLICIT_LIMIT_REFERENCE_REQUIRED")
        elif previous is not None and ref != previous:
            block("CORPORATE_ACTION_OR_REFERENCE_DISCONTINUITY")
        elif previous is None:
            first_unanchored = True
        previous = close
    return {"status": "BLOCK" if blockers else "CONDITIONAL_CONTINUOUS_REFERENCE_ONLY",
            "blockers": blockers, "sessions": len(rows),
            "first_reference_predecessor_unverified": first_unanchored,
            "complete_corporate_action_history_verified": False,
            "historical_vintage_verified": False, "actual_fills_verified": False,
            "decision_authority": False}
