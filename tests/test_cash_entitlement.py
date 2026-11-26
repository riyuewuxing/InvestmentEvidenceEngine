from dataclasses import replace
from datetime import date
from decimal import Decimal, localcontext

import pytest

from investment_evidence_engine.cash_entitlement import (
    CashEntitlementTerms,
    conditional_reference_price,
    reconcile_treasury_cancellation,
    terms_from_mapping,
    terms_to_mapping,
)


def terms():
    return CashEntitlementTerms(symbol="000035", disclosed_date=date(2025, 7, 30),
        record_date=date(2025, 8, 5), ex_date=date(2025, 8, 6),
        source_locator="https://example.invalid/fixture.pdf", total_shares=2500783182,
        excluded_shares=112750413, gross_per_share=Decimal("0.0352"),
        declared_total_cash=Decimal("84058753.47"),
        declared_reference_deduction=Decimal("0.0336129"))


def test_excluded_treasury_shares_distinguish_cash_and_reference():
    x = terms().checked()
    assert x["eligible_shares"] == 2388032769
    assert x["entitlement_minus_reference_cny"] == "0.0015871"
    assert conditional_reference_price(Decimal("5.00"), Decimal("0.0336129")) == Decimal("4.97")
    assert conditional_reference_price(Decimal("5.00"), Decimal("0.0352")) == Decimal("4.96")
    assert not x["actual_payment_verified"] and not x["historical_availability_verified"]


@pytest.mark.parametrize("changes", [
    {"excluded_shares": True}, {"excluded_shares": 2500783182}, {"total_shares": 0},
    {"gross_per_share": Decimal("NaN")}, {"gross_per_share": Decimal("0.0")},
    {"declared_reference_deduction": Decimal("0.0352")},
    {"declared_reference_deduction": Decimal("0.0336130")},
    {"declared_total_cash": Decimal("84058753.46")},
    {"ex_date": date(2025, 8, 5)}, {"source_locator": "http://example.invalid"},
])
def test_inconsistent_terms_fail_closed(changes):
    with pytest.raises(ValueError):
        replace(terms(), **changes).checked()


def test_cancellation_is_not_split_or_registration_date():
    params = {"before": 2500783182, "cancelled": 112750413, "after": 2388032769,
              "completed": date(2025, 10, 28), "disclosed": date(2025, 10, 30),
              "registration_completed": date(2025, 12, 4),
              "registration_disclosed": date(2025, 12, 5)}
    result = reconcile_treasury_cancellation(**params)
    assert result["issuer_reported_security_cancellation_date"] == "2025-10-28"
    assert result["issuer_reported_registration_change_date"] == "2025-12-04"
    assert not result["automatic_price_factor_allowed"] and not result["cash_entitlement_inferred"]
    with pytest.raises(ValueError):
        reconcile_treasury_cancellation(**(params | {"after": 2388032770}))
    with pytest.raises(ValueError):
        reconcile_treasury_cancellation(**(params | {"registration_completed": date(2025, 10, 27)}))


def test_no_excluded_shares_uses_direct_rate_not_rounded_total_division():
    x = replace(terms(), total_shares=2388032769, excluded_shares=0,
                gross_per_share=Decimal("0.036"), declared_total_cash=Decimal("85969179.68"),
                declared_reference_deduction=Decimal("0.036"))
    assert x.checked()["reference_deduction_per_share_cny"] == "0.036"
    assert x.checked()["rounding_profile"] == "TOTAL_CENT_HALF_UP_ALL_SHARES_DIRECT_RATE"
    with pytest.raises(ValueError, match="REFERENCE_RECONCILIATION"):
        replace(x, declared_reference_deduction=Decimal("0.0359999")).checked()


def test_decimal_computation_is_independent_of_ambient_precision():
    expected = terms().checked()
    with localcontext() as ctx:
        ctx.prec = 4
        assert terms().checked() == expected
        assert conditional_reference_price(Decimal("5.00"), Decimal("0.0336129")) == Decimal("4.97")


@pytest.mark.parametrize("key,value", [
    ("gross_per_share", 0.0352), ("gross_per_share", "3.52e-2"),
    ("gross_per_share", "00.0352"), ("gross_per_share", "0.0352000000000"),
    ("ex_date", "20250806"), ("record_date", "2025-8-5"), ("total_shares", True),
    ("total_shares", "2500783182"), ("extra", True),
])
def test_serialized_terms_refuse_coercions_and_unexpected_fields(key, value):
    with pytest.raises(ValueError):
        terms_from_mapping(terms_to_mapping(terms()) | {key: value})


def test_serialized_terms_roundtrip():
    assert terms_from_mapping(terms_to_mapping(terms())) == terms()
