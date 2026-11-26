"""Transparent conditional earnings/PE sensitivity and reverse valuation hurdles.

The current market capitalization is a caller-provided observation/proxy.
The model assumes the same share count and compares conditional terminal
equity market caps. Earnings, multiples, payouts, cost and hurdle inputs
are assumptions, not predictions, fair-value estimates or admitted facts.
No scenario probability is invented, so no expected return is emitted.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class EarningsCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)
    label: str = Field(min_length=1,max_length=100)
    annual_parent_profit_cny: FiniteFloat
    basis_note: str = Field(min_length=1,max_length=500)


class ProportionalCostAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)
    entry_cost_bps: FiniteFloat = Field(ge=0,lt=10000)
    exit_cost_bps: FiniteFloat = Field(ge=0,lt=10000)
    dividend_tax_pct: FiniteFloat = Field(ge=0,le=100)
    note: str = Field(min_length=1,max_length=500)
    status: Literal["ASSUMPTIONS_NOT_VERIFIED_BROKER_COSTS"] = "ASSUMPTIONS_NOT_VERIFIED_BROKER_COSTS"


class ValuationSensitivityInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)
    subject_id: str = Field(min_length=1,max_length=80)
    market_session: date
    horizon_calendar_days: int = Field(gt=0,le=1095)
    capitalization_cny: FiniteFloat = Field(gt=0)
    capitalization_basis_note: str = Field(min_length=1,max_length=500)
    reference_ttm_parent_profit_cny: FiniteFloat | None = None
    reference_profit_basis_note: str | None = Field(default=None,max_length=500)
    terminal_profit_cases: tuple[EarningsCase,...] = Field(default=(),max_length=12)
    terminal_pe_multiples: tuple[FiniteFloat,...] = Field(min_length=1,max_length=12)
    target_return_pcts: tuple[FiniteFloat,...] = Field(min_length=1,max_length=8)
    future_cash_distribution_yield_pct: FiniteFloat | None = Field(default=None,ge=0,lt=100)
    future_cash_distribution_basis_note: str | None = Field(default=None,max_length=500)
    costs: ProportionalCostAssumptions | None = None
    share_count_policy: Literal["UNCHANGED_SHARE_COUNT_ASSUMPTION"] = "UNCHANGED_SHARE_COUNT_ASSUMPTION"

    @model_validator(mode="after")
    def validate_inputs(self) -> ValuationSensitivityInputs:
        if any(not 0<x<=10000 for x in self.terminal_pe_multiples):
            raise ValueError("positive bounded terminal PE multiples required")
        if any(not -100<x<=10000 for x in self.target_return_pcts):
            raise ValueError("target return must exceed -100% and be bounded")
        if len(set(self.terminal_pe_multiples))!=len(self.terminal_pe_multiples):
            raise ValueError("duplicate PE assumptions")
        if len(set(self.target_return_pcts))!=len(self.target_return_pcts):
            raise ValueError("duplicate hurdle assumptions")
        if len({x.label for x in self.terminal_profit_cases})!=len(self.terminal_profit_cases):
            raise ValueError("duplicate scenario labels")
        if (self.reference_ttm_parent_profit_cny is None)!=(self.reference_profit_basis_note is None):
            raise ValueError("reference profit and its source note must be provided together")
        if self.reference_profit_basis_note is not None and not self.reference_profit_basis_note:
            raise ValueError("reference profit source note must not be blank")
        if (self.future_cash_distribution_yield_pct is None)!=(self.future_cash_distribution_basis_note is None):
            raise ValueError("future distribution assumption and note must be provided together")
        if self.future_cash_distribution_basis_note is not None and not self.future_cash_distribution_basis_note:
            raise ValueError("distribution basis note must not be blank")
        if self.costs is not None and self.future_cash_distribution_yield_pct is None:
            raise ValueError("conditional net return requires explicit distribution assumption including zero")
        return self


def _checked_number(value: float) -> float:
    # The strict Pydantic FiniteFloat also rejects overflow-derived inf/NaN.
    from math import isfinite

    if not isfinite(value):
        raise ValueError("nonfinite valuation result")
    return value


def valuation_sensitivity(inputs: ValuationSensitivityInputs) -> dict:
    inputs=ValuationSensitivityInputs.model_validate(inputs.model_dump())
    cap=inputs.capitalization_cny
    ref=inputs.reference_ttm_parent_profit_cny
    payout=None if inputs.future_cash_distribution_yield_pct is None else _checked_number(
        cap*inputs.future_cash_distribution_yield_pct/100)
    cost=inputs.costs
    entry=None if cost is None else _checked_number(cap*(1+cost.entry_cost_bps/10000))
    rows=[]
    for case in inputs.terminal_profit_cases:
        for multiple in inputs.terminal_pe_multiples:
            common={"case_label":case.label,"annual_parent_profit_cny":case.annual_parent_profit_cny,
                    "terminal_pe_multiple":multiple,"basis_note":case.basis_note}
            if case.annual_parent_profit_cny<=0:
                rows.append(common | {"status":"PE_NOT_APPLICABLE_TO_NONPOSITIVE_EARNINGS"})
                continue
            terminal=_checked_number(case.annual_parent_profit_cny*multiple)
            price_return=_checked_number((terminal/cap-1)*100)
            gross_total=None if payout is None else _checked_number(((terminal+payout)/cap-1)*100)
            net=None
            if cost is not None and entry is not None and payout is not None:
                terminal_net=terminal*(1-cost.exit_cost_bps/10000)+payout*(1-cost.dividend_tax_pct/100)
                net=_checked_number((terminal_net/entry-1)*100)
            rows.append(common | {"status":"CONDITIONAL_ONLY","terminal_capitalization_cny":terminal,
                "conditional_price_return_pct":price_return,"conditional_gross_total_return_pct":gross_total,
                "conditional_net_return_pct":net})
    hurdles=[]
    for multiple in inputs.terminal_pe_multiples:
        for target in inputs.target_return_pcts:
            target_cap=_checked_number(cap*(1+target/100))
            required=_checked_number(target_cap/multiple)
            net_required=None
            if cost is not None and entry is not None and payout is not None:
                # If the specified cash assumption alone exceeds the hurdle,
                # no positive terminal capitalization is required by this
                # algebra; do not call that a valid zero-PE valuation.
                target_net_cap=(entry*(1+target/100)-payout*(1-cost.dividend_tax_pct/100))/(1-cost.exit_cost_bps/10000)
                net_required=_checked_number(max(0.,target_net_cap)/multiple)
            hurdles.append({"terminal_pe_multiple":multiple,"target_return_pct":target,
                "required_profit_for_price_return_cny":required,
                "required_profit_to_reference_ttm_x":None if ref is None or ref<=0 else _checked_number(required/ref),
                "required_profit_for_conditional_net_return_cny":net_required,
                "net_hurdle_cash_assumption_alone_covers":None if net_required is None else net_required==0})
    return {"status":"CONDITIONAL_VALUATION_SENSITIVITY_ONLY","inputs":inputs.model_dump(mode="json"),
        "current_implied_pe_on_reference_profit":None if ref is None or ref<=0 else _checked_number(cap/ref),
        "scenarios":rows,"reverse_hurdles":hurdles,
        "net_return_cost_basis":"PROPORTIONAL_NOTIONAL_ONLY_EXCLUDES_MINIMUM_FEES_AND_UNMODELED_COSTS" if cost else "NOT_SUPPLIED",
        "expected_return_estimated":False,"scenario_probabilities_estimated":False,
        "fair_value_estimated":False,"historical_vintage_verified":False,
        "decision_authority":False,"research_only":True,"execution_allowed":False}
