"""Cash entitlement versus exchange reference: exact, conditional arithmetic.

A distribution with excluded treasury shares can have distinct shareholder
cash and theoretical ex-price deductions. Neither is actual account cash,
a complete action history, or a vendor adjustment factor.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from urllib.parse import urlsplit

CENT = Decimal("0.01")
REFERENCE_QUANTUM = Decimal("0.0000001")


def _amount(value: Decimal, *, positive: bool = True) -> Decimal:
    if (type(value) is not Decimal or not value.is_finite() or
            (value <= 0 if positive else value < 0) or value > Decimal("1000000000000000")
            or value.as_tuple().exponent < -12):
        raise ValueError("CASH_TERMS_AMOUNT_INVALID")
    return value


def _shares(value: int, *, positive: bool = True) -> int:
    if type(value) is not int or not (int(positive) <= value <= 10**15):
        raise ValueError("CASH_TERMS_SHARE_COUNT_INVALID")
    return value


@dataclass(frozen=True)
class CashEntitlementTerms:
    """An explicit reviewed disclosure, not an admitted historical observation."""

    symbol: str
    disclosed_date: date
    record_date: date
    ex_date: date
    source_locator: str
    total_shares: int
    excluded_shares: int
    gross_per_share: Decimal
    declared_total_cash: Decimal
    declared_reference_deduction: Decimal

    def checked(self) -> dict:
        if (not isinstance(self.symbol, str) or re.fullmatch(r"[0-9]{6}", self.symbol) is None
                or any(type(d) is not date for d in (self.disclosed_date, self.record_date, self.ex_date))
                or not self.disclosed_date <= self.record_date < self.ex_date
                or not isinstance(self.source_locator, str) or len(self.source_locator) > 1024):
            raise ValueError("CASH_TERMS_IDENTITY_OR_DATE_INVALID")
        url = urlsplit(self.source_locator)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError("CASH_TERMS_LOCATOR_INVALID")
        total = _shares(self.total_shares)
        excluded = _shares(self.excluded_shares, positive=False)
        if excluded >= total:
            raise ValueError("CASH_TERMS_ELIGIBLE_SHARE_COUNT_INVALID")
        gross = _amount(self.gross_per_share)
        declared = _amount(self.declared_total_cash)
        reference = _amount(self.declared_reference_deduction, positive=False)
        eligible = total - excluded
        # This profile explicitly uses the reviewed disclosure's cent rounding
        # and seven-decimal truncation, not a universal exchange rule.
        computed_total = (Decimal(eligible) * gross).quantize(CENT, rounding=ROUND_HALF_UP)
        if declared != computed_total:
            raise ValueError("CASH_TERMS_TOTAL_RECONCILIATION_MISMATCH")
        computed_reference = (declared / Decimal(total)).quantize(REFERENCE_QUANTUM, rounding=ROUND_DOWN)
        if reference != computed_reference:
            raise ValueError("CASH_TERMS_REFERENCE_RECONCILIATION_MISMATCH")
        return {"symbol": self.symbol, "disclosed_date": self.disclosed_date.isoformat(),
                "record_date": self.record_date.isoformat(), "ex_date": self.ex_date.isoformat(),
                "source_locator": self.source_locator, "total_shares": total,
                "excluded_shares": excluded, "eligible_shares": eligible,
                "gross_entitlement_per_share_cny": str(gross),
                "declared_total_cash_cny": str(declared),
                "reference_deduction_per_share_cny": str(reference),
                "entitlement_minus_reference_cny": str(gross-reference),
                "rounding_profile": "TOTAL_CENT_HALF_UP_REFERENCE_7DP_TRUNCATE",
                "actual_payment_verified": False, "historical_availability_verified": False,
                "corporate_action_coverage_verified": False, "decision_authority": False}


def conditional_reference_price(prior_close: Decimal, deduction: Decimal) -> Decimal:
    prior = _amount(prior_close)
    deduction = _amount(deduction, positive=False)
    value = (prior-deduction).quantize(CENT, rounding=ROUND_HALF_UP)
    if value <= 0:
        raise ValueError("CASH_TERMS_NONPOSITIVE_REFERENCE")
    return value


def reconcile_treasury_cancellation(*, before: int, cancelled: int, after: int,
                                   completed: date, disclosed: date,
                                   registration_completed: date,
                                   registration_disclosed: date) -> dict:
    """Reconcile an issuer-reported treasury cancellation; never a split."""
    for v in (before, cancelled, after):
        _shares(v)
    if before-cancelled != after:
        raise ValueError("TREASURY_SHARE_RECONCILIATION_MISMATCH")
    if (any(type(d) is not date for d in (completed, disclosed, registration_completed,
                                         registration_disclosed))
            or not completed <= disclosed <= registration_completed <= registration_disclosed):
        raise ValueError("TREASURY_EVENT_DATE_ORDER_INVALID")
    return {"total_before": before, "treasury_cancelled": cancelled, "total_after": after,
            "issuer_reported_security_cancellation_date": completed.isoformat(),
            "cancellation_document_date": disclosed.isoformat(),
            "issuer_reported_registration_change_date": registration_completed.isoformat(),
            "registration_document_date": registration_disclosed.isoformat(),
            "event_type": "ISSUER_REPORTED_TREASURY_SHARE_CANCELLATION",
            "shareholder_units_changed_inferred": False,
            "automatic_price_factor_allowed": False, "cash_entitlement_inferred": False,
            "independent_registry_verified": False, "historical_availability_verified": False,
            "decision_authority": False}
