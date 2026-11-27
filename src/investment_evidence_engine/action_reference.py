"""Audit vendor raw closes, previous-close references, and action dates.

A successful result reconciles one observed vendor interval against a
second close series and a caller-supplied issuer cash-event list. This
does not establish exhaustive issuer history, historic data vintage,
share splits, rights subscriptions, or actual after-tax total return.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import subprocess
import sys
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat

from .cash_entitlement import CashEntitlementTerms
from .historical_capture import SH, PublicSecurity, validate_symbol_window, validate_window
from .historical_reference import HistoricalCloseSeries
from .holding_risk import CashDistributionInputs
from .market_calendar import CalendarObservation, check_calendar

MAX_CHILD_BYTES=256*1024


class PreviousCloseRow(BaseModel):
    model_config=ConfigDict(extra="forbid",frozen=True,strict=True)
    session: date
    close: FiniteFloat=Field(gt=0)
    previous_reference: FiniteFloat=Field(gt=0)


class AdjustmentDateRow(BaseModel):
    model_config=ConfigDict(extra="forbid",frozen=True,strict=True)
    effective_date: date
    forward_factor: FiniteFloat=Field(gt=0)
    backward_factor: FiniteFloat=Field(gt=0)
    adjustment_factor: FiniteFloat=Field(gt=0)


class ActionObservation(BaseModel):
    model_config=ConfigDict(extra="forbid",frozen=True,strict=True)
    subject: PublicSecurity
    first_requested: date
    last_requested: date
    observed_at: AwareDatetime
    raw_rows: tuple[PreviousCloseRow,...]=Field(min_length=21,max_length=756)
    factors: tuple[AdjustmentDateRow,...]=Field(max_length=100)


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)


def bind_cash_reference_terms(events: CashDistributionInputs, subject: PublicSecurity,
                              sessions: tuple[date, ...],
                              reference_terms: tuple[CashEntitlementTerms, ...] = ()) -> tuple[dict, list, dict]:
    """Validate exact included cash events and explicit deductions before network acquisition.

    This is source-scope and arithmetic validation only, not proof of original
    bytes, vintage, or completeness.
    """
    events = CashDistributionInputs.model_validate(events.model_dump())
    subject.prefixed
    if (subject.asset_type != "STOCK" or not isinstance(sessions, tuple) or not sessions
            or any(type(day) is not date for day in sessions)
            or tuple(sorted(set(sessions))) != sessions):
        raise ValueError("ACTION_REFERENCE_SESSION_OR_SUBJECT_SCOPE_INVALID")
    validate_symbol_window(subject, sessions[0], sessions[-1])
    included={}
    excluded=[]
    seen=set()
    for event in events.events:
        if (event.subject_id!=subject.symbol or event.disclosed_date>event.ex_date
                or not event.source_locator.startswith("https://") or event.ex_date in seen):
            raise ValueError("ACTION_CASH_EVENT_IDENTITY_OR_DATE_INVALID")
        seen.add(event.ex_date)
        if event.ex_date<=sessions[0] or event.ex_date>sessions[-1]:
            excluded.append({"ex_date":event.ex_date.isoformat(),"reason":"OUTSIDE_HOLDING_WINDOW"})
            continue
        if event.ex_date not in sessions:
            raise ValueError("ACTION_CASH_EVENT_NON_SESSION")
        included[event.ex_date]=event
    # Shareholder cash and the disclosed ex-reference deduction are distinct
    # for a distribution excluding treasury shares. A legacy caller can only
    # obtain a conditional equal-deduction comparison, not source verification.
    if not isinstance(reference_terms, tuple) or len(reference_terms) > 100:
        raise ValueError("ACTION_REFERENCE_TERMS_SCHEMA")
    explicit = {}
    for terms in reference_terms:
        if type(terms) is not CashEntitlementTerms:
            raise ValueError("ACTION_REFERENCE_TERMS_SCHEMA")
        receipt = terms.checked()
        event = included.get(terms.ex_date)
        if (event is None or terms.ex_date in explicit
                or terms.symbol != subject.symbol or terms.symbol != event.subject_id
                or terms.disclosed_date != event.disclosed_date
                or terms.source_locator != event.source_locator
                or terms.gross_per_share != Decimal(str(event.gross_cash_per_unit_cny))
                or terms.record_date != sessions[sessions.index(terms.ex_date)-1]):
            raise ValueError("ACTION_REFERENCE_TERMS_SCOPE_OR_CASH_MISMATCH")
        explicit[terms.ex_date] = (terms.declared_reference_deduction, receipt)
    return included, excluded, explicit


def audit_cash_actions(obs: ActionObservation, other_close: HistoricalCloseSeries,
                       calendar: CalendarObservation, events: CashDistributionInputs, *, now: datetime,
                       reference_terms: tuple[CashEntitlementTerms, ...] = ()) -> dict:
    obs=ActionObservation.model_validate(obs.model_dump())
    other_close=HistoricalCloseSeries.model_validate(other_close.model_dump())
    obs.subject.prefixed
    if (obs.subject.asset_type!="STOCK" or now.utcoffset() is None or obs.observed_at>now
            or other_close.subject_id!=obs.subject.symbol or other_close.source_label=="baostock"
            or other_close.currency!="CNY" or other_close.price_basis!="RAW_CLOSE"):
        raise ValueError("ACTION_SCOPE_OR_BASIS_INVALID")
    validate_symbol_window(obs.subject, obs.first_requested, obs.last_requested)
    sessions=check_calendar(calendar,first=obs.first_requested,last=obs.last_requested,cutoff=now)
    if tuple(r.session for r in obs.raw_rows)!=sessions or tuple(r.session for r in other_close.closes)!=sessions:
        raise ValueError("ACTION_PRICE_SESSION_COVERAGE_MISMATCH")
    if any(abs(r.close-s.close)>0.011 for r,s in zip(obs.raw_rows,other_close.closes)):
        raise ValueError("ACTION_RAW_CLOSE_CROSSCHECK_MISMATCH")
    factor_dates=tuple(r.effective_date for r in obs.factors)
    if factor_dates!=tuple(sorted(set(factor_dates))) or any(d not in sessions for d in factor_dates):
        raise ValueError("ACTION_FACTOR_DATE_SCOPE_INVALID")
    included, excluded, explicit = bind_cash_reference_terms(events, obs.subject, sessions, reference_terms)
    factors=set(factor_dates)-{sessions[0]}
    audit=[]
    errors=[]
    for previous,current in zip(obs.raw_rows[:-1],obs.raw_rows[1:]):
        prev=Decimal(str(previous.close))
        ref=Decimal(str(current.previous_reference))
        change=ref!=_money(prev)
        event=included.get(current.session)
        factor=current.session in factors
        if event is None and not change and not factor:
            continue
        cash=Decimal(str(event.gross_cash_per_unit_cny)) if event else Decimal(0)
        terms = explicit.get(current.session)
        deduction = terms[0] if terms else cash
        expected=_money(prev-deduction)
        # Exact cent-rounded theoretical reference for the selected convention.
        # A rights issue, split, or incompatible convention is not coerced.
        matched=bool(event and factor and expected>0 and ref==expected)
        if not matched:
            errors.append("UNRECONCILED_ACTION_OR_REFERENCE")
        audit.append({"session":current.session.isoformat(),"prior_raw_close":float(prev),
            "observed_previous_reference":float(ref),"cash_event_gross_cny":float(cash) if event else None,
            "expected_cash_only_reference":float(expected),"vendor_factor_date_present":factor,
            "reference_deduction_cny":str(deduction) if event else None,
            "reference_deduction_basis":("EXPLICIT_DISCLOSED_TERMS_RECONCILED" if terms
                else "ASSUMED_EQUAL_TO_GROSS_ENTITLEMENT" if event else "NO_EXPLICIT_CASH_EVENT"),
            "reference_terms":terms[1] if terms else None,
            "issuer_locator":event.source_locator if event else None,
            "status":"CASH_ONLY_REFERENCE_MATCH" if matched else "BLOCKED"})
    return {"status":"BLOCKED" if errors else "OBSERVED_ACTION_INTERVAL_RECONCILED",
        "subject":obs.subject.model_dump(mode="json"),"first_session":sessions[0].isoformat(),
        "last_session":sessions[-1].isoformat(),"session_count":len(sessions),
        "observed_at":obs.observed_at.isoformat(),"comparison_source":other_close.source_label,
        "vendor_factor_dates":[d.isoformat() for d in factor_dates],
        "first_session_factor_excluded":sessions[0] in factor_dates,
        "event_audit":audit,"excluded_explicit_events":excluded,"error_codes":sorted(set(errors)),
        "normalized_observation_sha256":hashlib.sha256(obs.model_dump_json().encode()).hexdigest(),
        "explicit_reference_terms_count":len(explicit),
        "all_included_cash_reference_terms_explicit":bool(included) and len(explicit)==len(included),
        "legacy_equal_deduction_assumption_count":len(included)-len(explicit),
        "reference_terms_original_source_independently_verified":False,
        "official_issuer_event_universe_verified":False,"factor_numeric_semantics_verified":False,
        "corporate_action_coverage_verified":False,"historical_vintage_verified":False,
        "raw_provider_bytes_retained":False,"decision_authority":False,"research_only":True,
        "execution_allowed":False}


def _rows(rs, fields: list[str],limit: int) -> list:
    if rs.error_code!="0" or list(rs.fields)!=fields:
        raise ValueError("ACTION_VENDOR_SCHEMA_OR_QUERY_FAILURE")
    rows=[]
    while rs.next():
        if len(rows)>=limit:
            raise ValueError("ACTION_VENDOR_ROW_LIMIT")
        row=rs.get_row_data()
        if len(row)!=len(fields):
            raise ValueError("ACTION_VENDOR_ROW_SCHEMA")
        rows.append(row)
    if rs.error_code!="0":
        raise ValueError("ACTION_VENDOR_QUERY_FAILURE")
    return rows


def _acquire(subject: PublicSecurity,first: date,last: date) -> ActionObservation:
    import baostock as bs

    if subject.asset_type!="STOCK":
        raise ValueError("ACTION_STOCK_ONLY")
    validate_window(first,last,datetime.now(SH))
    validate_symbol_window(subject, first, last)
    identity=subject.prefixed[:2]+"."+subject.symbol
    login=bs.login()
    if login.error_code!="0":
        raise ValueError("ACTION_VENDOR_LOGIN_FAILURE")
    try:
        fields=["date","code","close","preclose","adjustflag","tradestatus"]
        raw=_rows(bs.query_history_k_data_plus(identity,",".join(fields),start_date=first.isoformat(),
            end_date=last.isoformat(),frequency="d",adjustflag="3"),fields,756)
        factor_fields=["code","dividOperateDate","foreAdjustFactor","backAdjustFactor","adjustFactor"]
        factors=_rows(bs.query_adjust_factor(code=identity,start_date=first.isoformat(),end_date=last.isoformat()),
                      factor_fields,100)
    finally:
        bs.logout()
    if any(r[1]!=identity or r[4]!="3" or r[5]!="1" for r in raw):
        raise ValueError("ACTION_RAW_IDENTITY_BASIS_OR_SUSPENSION")
    if any(r[0]!=identity for r in factors):
        raise ValueError("ACTION_FACTOR_IDENTITY_MISMATCH")
    return ActionObservation(subject=subject,first_requested=first,last_requested=last,
        observed_at=datetime.now(SH),
        raw_rows=tuple(PreviousCloseRow(session=date.fromisoformat(r[0]),close=float(r[2]),
                      previous_reference=float(r[3])) for r in raw),
        factors=tuple(AdjustmentDateRow(effective_date=date.fromisoformat(r[1]),forward_factor=float(r[2]),
                      backward_factor=float(r[3]),adjustment_factor=float(r[4])) for r in factors))


def _child(symbol: str,first: str,last: str) -> None:
    try:
        subject=PublicSecurity(symbol=symbol,asset_type="STOCK")
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            observed=_acquire(subject,date.fromisoformat(first),date.fromisoformat(last))
        print(json.dumps({"status":"OBSERVED","observation":observed.model_dump(mode="json")},allow_nan=False))
    except Exception as exc:
        code=str(exc)
        if not re.fullmatch(r"[A-Z0-9_]{1,100}",code):
            code=type(exc).__name__
        print(json.dumps({"status":"BLOCKED","error_code":code}))


def acquire_action_observation(subject: PublicSecurity,first: date,last: date) -> ActionObservation:
    if subject.asset_type!="STOCK":
        raise ValueError("ACTION_STOCK_ONLY")
    subject.prefixed
    validate_window(first,last,datetime.now(SH))
    validate_symbol_window(subject, first, last)
    try:
        proc=subprocess.run([sys.executable,"-m",__name__,"--child",subject.symbol,first.isoformat(),last.isoformat()],
                            capture_output=True,check=False,timeout=35)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("ACTION_WATCHDOG_TIMEOUT") from exc
    if proc.returncode or len(proc.stdout)>MAX_CHILD_BYTES:
        raise ValueError("ACTION_CHILD_EXIT_OR_OUTPUT_LIMIT")
    data=json.loads(proc.stdout)
    if not isinstance(data,dict) or data.get("status")!="OBSERVED":
        code=data.get("error_code") if isinstance(data,dict) else None
        raise ValueError(code if isinstance(code,str) and re.fullmatch(r"[A-Za-z0-9_]{1,100}",code)
                         else "ACTION_CHILD_BLOCKED")
    observed=ActionObservation.model_validate_json(json.dumps(data["observation"]))
    if observed.subject!=subject or (observed.first_requested,observed.last_requested)!=(first,last):
        raise ValueError("ACTION_CHILD_SCOPE_MISMATCH")
    return observed


if __name__=="__main__":
    if len(sys.argv)!=5 or sys.argv[1]!="--child":
        raise SystemExit(2)
    _child(*sys.argv[2:])
