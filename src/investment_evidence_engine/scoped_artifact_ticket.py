"""Short-lived artifact ticket: authenticate claimed digest before any expensive read.

The ticket is a bearer capability for one scope and one byte digest; it is not
single-use, a signature of an artifact publisher, or proof of device identity.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time

MAX_TTL_SECONDS = 300
_DIGEST = re.compile(r"[0-9a-f]{64}")
_SCOPE = re.compile(r"[a-z][a-z0-9-]{0,63}")
_TICKET = re.compile(r"v2\.([0-9]{1,12})\.([0-9a-f]{64})\.([0-9a-f]{64})")


def _message(scope: str, expires: int, digest: str) -> bytes:
    return f"v2:{scope}:{expires}:{digest}".encode("ascii")


def issue_ticket(
    scope: str, secret: str, digest: str, *, ttl_seconds: int, now_ts: int | None = None
) -> str:
    if not _SCOPE.fullmatch(scope) or not _DIGEST.fullmatch(digest) or not secret:
        raise ValueError("INVALID_TICKET_INPUT")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
        raise ValueError("INVALID_TICKET_TTL")
    if not 1 <= ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError("INVALID_TICKET_TTL")
    now = int(time.time()) if now_ts is None else now_ts
    expires = now + ttl_seconds
    if not 0 <= now <= expires < 10**12:
        raise ValueError("INVALID_TICKET_CLOCK")
    signature = hmac.new(secret.encode("utf-8"), _message(scope, expires, digest), hashlib.sha256)
    return f"v2.{expires}.{digest}.{signature.hexdigest()}"


def authenticated_ticket_digest(
    scope: str, ticket: str | None, secret: str, *, now_ts: int | None = None
) -> str | None:
    """Cheap pre-authentication; must still match the actual returned bytes."""
    if not ticket or not secret or not _SCOPE.fullmatch(scope):
        return None
    match = _TICKET.fullmatch(ticket)
    if match is None:
        return None
    expires = int(match[1])
    digest, signature = match[2], match[3]
    now = int(time.time()) if now_ts is None else now_ts
    if not 0 <= now < expires <= now + MAX_TTL_SECONDS:
        return None
    expected = hmac.new(
        secret.encode("utf-8"), _message(scope, expires, digest), hashlib.sha256
    ).hexdigest()
    return digest if hmac.compare_digest(signature, expected) else None


def matches_observed_digest(
    scope: str, ticket: str | None, secret: str, observed: str, *, now_ts: int | None = None
) -> bool:
    digest = authenticated_ticket_digest(scope, ticket, secret, now_ts=now_ts)
    return digest is not None and bool(_DIGEST.fullmatch(observed)) and hmac.compare_digest(
        digest, observed
    )
