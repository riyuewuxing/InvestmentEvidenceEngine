"""Uniform nominal tax-tier sensitivity, never a shareholder's assessed tax.

The reviewed 2015 listed-stock rule has three effective rates. Without an
actual acquisition/transfer settlement ledger, no rate is assigned to a holder.
Do not subtract tax from the price-only sleeve or claim a cash payment.
"""
from __future__ import annotations

import math
from decimal import Decimal, localcontext

TAX_RATES = (Decimal("0"), Decimal("0.10"), Decimal("0.20"))
SCOPE = "CONDITIONAL_ORDINARY_DOMESTIC_LISTED_STOCK_INDIVIDUAL_2015_RULE"
RULE_URLS = (
    "https://www.chinatax.gov.cn/chinatax/n810341/n810755/c1797427/content.html",
    "https://shanghai.chinatax.gov.cn/zcfw/zcjd/201509/t419000.html",
)


def uniform_tax_tiers(price_change_pct: float, gross_entitlement_increment_pp: float) -> dict:
    """Apply the same hypothetical tax rate to all known gross entitlements.

    Returns are on the initial segment wealth basis, before actual cost and
    cash settlement reconciliation. The three cases are not probabilities.
    """
    if (type(price_change_pct) not in {float, int}
            or type(gross_entitlement_increment_pp) not in {float, int}
            or not math.isfinite(price_change_pct) or not math.isfinite(gross_entitlement_increment_pp)
            or price_change_pct <= -100 or gross_entitlement_increment_pp < 0):
        raise ValueError("DIVIDEND_TAX_SCENARIO_INPUT")
    with localcontext() as ctx:
        ctx.prec = 64
        price, gross = Decimal(str(price_change_pct)), Decimal(str(gross_entitlement_increment_pp))
        rows = []
        for rate in TAX_RATES:
            tax = gross*rate
            net = gross-tax
            rows.append({"uniform_assumed_tax_rate_pct": str(rate*100),
                         "nominal_tax_increment_pp": str(tax),
                         "nominal_net_entitlement_increment_pp": str(net),
                         "price_plus_nominal_net_entitlement_change_pct": str(price+net)})
    return {"status": "CONDITIONAL_UNIFORM_TAX_TIERS_ONLY", "scope": SCOPE,
            "price_only_change_pct": str(price), "gross_entitlement_increment_pp": str(gross),
            "scenarios": rows, "rule_urls": list(RULE_URLS),
            "actual_holding_period_verified": False, "actual_tax_withholding_verified": False,
            "actual_payment_verified": False, "actual_costs_verified": False,
            "actual_tax_rate_assigned": False, "total_return_certified": False,
            "decision_authority": False, "execution_allowed": False, "pit_safe": False}
