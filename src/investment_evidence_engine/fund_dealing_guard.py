"""Conservative research diagnostics; neither order routing nor acceptance evidence."""
from datetime import datetime
from decimal import Decimal

from .evidence_time_guard import SHANGHAI, aware, source_visible


def pcf_channel_diagnostic(*, effective_date: datetime | None, effective_at: datetime,
                           available_at: datetime | None, ingested_at: datetime | None,
                           cutoff: datetime, creation_allowed: bool | None,
                           redemption_allowed: bool | None) -> dict:
    """Only same-session, actually captured, explicit direction flags qualify."""
    result = {
        "status": "NO_VISIBLE_SAME_SESSION_PCF",
        "creation_allowed_reported": None,
        "redemption_allowed_reported": None,
        "secondary_trading_status_inferred": False,
        "actual_order_acceptance_verified": False,
        "decision_authority": False,
    }
    if not aware(effective_date) or not aware(effective_at):
        return result
    if not source_visible(available_at=available_at, retrieved_at=ingested_at,
                          published_at=None, cutoff=cutoff):
        return result
    if effective_date.astimezone(SHANGHAI).date() != effective_at.astimezone(SHANGHAI).date():
        return result | {"status": "PCF_OTHER_SESSION_REFERENCE_ONLY"}
    if effective_date > effective_at:
        return result
    if ingested_at > effective_at:
        return result | {"status": "PCF_CAPTURE_AFTER_QUERY_TIME_REFERENCE_ONLY"}
    creation = creation_allowed if type(creation_allowed) is bool else None
    redemption = redemption_allowed if type(redemption_allowed) is bool else None
    return result | {
        "status": ("SAME_SESSION_REPORTED_FLAGS" if creation is not None and redemption is not None
                   else "SAME_SESSION_FLAGS_INCOMPLETE"),
        "creation_allowed_reported": creation,
        "redemption_allowed_reported": redemption,
    }


def combined_subscription_cap_status(*, requested_cny: Decimal,
                                     verified_prior_cny: Decimal | None,
                                     aggregate_complete: bool,
                                     cap_cny: Decimal,
                                     inclusive: bool | None) -> str:
    """One account, same fund/day, all covered classes/channels/operations.

    Prior amount must be verified for exactly that scope. No assumptions about
    unknown account activity or ambiguous equal-limit wording. All positive
    results are numeric comparisons, not a trade acceptance prediction.
    """
    for value in (requested_cny, cap_cny):
        if type(value) is not Decimal or not value.is_finite() or value <= 0:
            raise ValueError("invalid positive monetary amount")
    if verified_prior_cny is not None and (type(verified_prior_cny) is not Decimal
            or not verified_prior_cny.is_finite() or verified_prior_cny < 0):
        raise ValueError("invalid prior amount")
    if type(aggregate_complete) is not bool or (inclusive is not None and type(inclusive) is not bool):
        raise ValueError("invalid scope or boundary flag")
    if requested_cny > cap_cny:
        return "EXCEEDS_REPORTED_CAP_REJECTION_POSSIBLE"
    if aggregate_complete is not True or verified_prior_cny is None:
        return "AGGREGATE_UNKNOWN"
    total = requested_cny + verified_prior_cny
    if total > cap_cny or (total == cap_cny and inclusive is False):
        return "EXCEEDS_REPORTED_CAP_REJECTION_POSSIBLE"
    if total == cap_cny and inclusive is None:
        return "EXACT_CAP_WORDING_AMBIGUOUS"
    return "WITHIN_REPORTED_CAP_NOT_ACCEPTANCE"
