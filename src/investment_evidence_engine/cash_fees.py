"""Cash-market transaction cost scenarios; no broker account or execution.

Rates reviewed for ordinary domestic A shares and equity ETFs on SSE/SZSE.
The regulatory component is separated from explicit hypothetical broker
commission (inclusive of exchange and regulatory fees) and from quote spread.
No estimated impact, future fill or total fund holding cost is inferred.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from .historical_capture import PublicSecurity, validate_symbol_window
from .market_calendar import scheduled_days

RULE_VERSION = "CN_CASH_2026_11_REVIEWED_V1"
FIRST = date(2026, 1, 1)
LAST = date(2026, 11, 26)
RULE_SOURCES = (
    "https://one.sse.com.cn/onething/gptz/",
    "https://www.szse.cn/marketServices/deal/payFees/",
    "https://www.sse.com.cn/services/tradingservice/charge/ssecharge/",
    "https://www.mof.gov.cn/jrttts/202308/t20230828_3904235.htm",
    "https://shanghai.chinatax.gov.cn/zcfw/zcfgk/yhs/202106/t458595.html",
    "https://neris.csrc.gov.cn/falvfagui/rdqsHeader/mainbody?navbarId=3&secFutrsLawId=b25a17fb262742f2aea99515380cf3bb",
    "https://investor.szse.cn/warning/activities/fundIntroduction/t20210104_584079.html",
)


def _d(value: float | int | str) -> Decimal:
    return Decimal(str(value))


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)


class CommissionScenario(BaseModel):
    model_config = ConfigDict(extra="forbid",frozen=True,strict=True,str_strip_whitespace=True)
    inclusive_rate_bps: FiniteFloat = Field(ge=0,le=30)
    minimum_per_order_cny: FiniteFloat = Field(ge=5,le=1000)
    note: str = Field(min_length=1,max_length=400)
    basis: Literal["ASSUMED_INCLUSIVE_COMMISSION_EXCLUDES_TRANSFER_AND_STAMP_TAX"] = "ASSUMED_INCLUSIVE_COMMISSION_EXCLUDES_TRANSFER_AND_STAMP_TAX"


class CashFeeScenario(BaseModel):
    model_config = ConfigDict(extra="forbid",frozen=True,strict=True)
    subject: PublicSecurity
    kind: Literal["DOMESTIC_A_STOCK","DOMESTIC_EQUITY_ETF_SECONDARY"]
    reference_session: date
    entry_notional_cny: FiniteFloat = Field(gt=0,le=1e10)
    exit_notional_cny: FiniteFloat = Field(gt=0,le=1e10)
    entry_orders: int = Field(ge=1,le=100)
    exit_orders: int = Field(ge=1,le=100)
    commission: CommissionScenario | None = None

    @model_validator(mode="after")
    def valid_scope(self) -> CashFeeScenario:
        self.subject.prefixed
        validate_symbol_window(self.subject, self.reference_session, self.reference_session)
        if (self.kind=="DOMESTIC_A_STOCK") != (self.subject.asset_type=="STOCK"):
            raise ValueError("ASSET_KIND_MISMATCH")
        if not FIRST<=self.reference_session<=LAST or not scheduled_days(self.reference_session,self.reference_session)[0].is_trading_day:
            raise ValueError("FEE_RULE_DATE_UNSUPPORTED")
        for amount,orders in ((self.entry_notional_cny,self.entry_orders),(self.exit_notional_cny,self.exit_orders)):
            cents=_d(amount)*100
            if cents!=cents.to_integral_value() or cents<orders:
                raise ValueError("ORDER_AMOUNT_CENT_PRECISION_OR_COUNT_INVALID")
        # Published minimum for inclusive commission, not a broker quote.
        floor=0.541 if self.kind=="DOMESTIC_A_STOCK" else 0.4
        if self.commission is not None and self.commission.inclusive_rate_bps<floor:
            raise ValueError("COMMISSION_BELOW_REVIEWED_INCLUDED_REGULATORY_RATE")
        return self


def fee_scenario(inputs: CashFeeScenario) -> dict:
    inputs=CashFeeScenario.model_validate(inputs.model_dump())
    stock=inputs.kind=="DOMESTIC_A_STOCK"
    regulatory_rate=_d("0.0000541" if stock else "0.00004")
    transfer_rate=_d("0.00001" if stock else "0")
    stamp_rate=_d("0.0005" if stock else "0")
    def leg(notional: float, orders: int, sell: bool) -> dict:
        total=_d(notional)
        # Allocate whole cents exactly: at most one-cent difference across
        # hypothetical orders. No silent multiplication of an unrounded order.
        cents,remainder=divmod(int(total*100),orders)
        sizes=[Decimal(cents+(i<remainder))/100 for i in range(orders)]
        embedded=sum((_money(per*regulatory_rate) for per in sizes),Decimal(0))
        transfer=sum((_money(per*transfer_rate) for per in sizes),Decimal(0))
        stamp=sum((_money(per*(stamp_rate if sell else Decimal(0))) for per in sizes),Decimal(0))
        explicit=transfer+stamp
        commission=None
        if inputs.commission is not None:
            commission=sum((_money(max(per*_d(inputs.commission.inclusive_rate_bps)/10000,
                                  _d(inputs.commission.minimum_per_order_cny))) for per in sizes),Decimal(0))
        return {"notional_cny":float(total),"equal_size_orders":orders,
            "embedded_regulatory_fee_reference_cny":float(embedded),
            "transfer_fee_reference_cny":float(transfer),"stamp_tax_reference_cny":float(stamp),
            "separate_public_fee_reference_cny":float(explicit),
            "inclusive_commission_scenario_cny":None if commission is None else float(commission),
            "explicit_fee_scenario_cny":None if commission is None else float(commission+explicit)}
    buy=leg(inputs.entry_notional_cny,inputs.entry_orders,False)
    sell=leg(inputs.exit_notional_cny,inputs.exit_orders,True)
    fee=None
    fee_only_return=None
    if inputs.commission is not None:
        fee=float(_d(buy["explicit_fee_scenario_cny"])+_d(sell["explicit_fee_scenario_cny"]))
        paid=_d(inputs.entry_notional_cny)+_d(buy["explicit_fee_scenario_cny"])
        received=_d(inputs.exit_notional_cny)-_d(sell["explicit_fee_scenario_cny"])
        fee_only_return=float((received/paid-1)*100)
    return {"status":"CONDITIONAL_EXPLICIT_CASH_FEES_ONLY","inputs":inputs.model_dump(mode="json"),
        "rule_version":RULE_VERSION,"rule_sources":list(RULE_SOURCES),
        "scope_note":"SSE_SZSE_ORDINARY_DOMESTIC_A_STOCK_OR_EQUITY_ETF_SECONDARY",
        "buy":buy,"sell":sell,"round_trip_explicit_fee_cny":fee,
        "round_trip_explicit_fee_bps_of_entry":None if fee is None else fee/inputs.entry_notional_cny*10000,
        "gross_price_change_pct":float((_d(inputs.exit_notional_cny)/_d(inputs.entry_notional_cny)-1)*100),
        "conditional_fee_only_net_return_pct":fee_only_return,
        "commission_known":False,"actual_broker_fee_verified":False,
        "future_fee_schedule_verified":False,"impact_cost_estimated":False,
        "spread_cost_estimated":False,"total_holding_cost_estimated":False,
        "formal_liquidity_cost_estimated":False,"decision_authority":False,
        "research_only":True,"execution_allowed":False,
        "rounding_note":"EQUAL_SIZE_WHOLE_CENT_ORDER_HALF_UP_SCENARIO_NOT_BROKER_SETTLEMENT"}
