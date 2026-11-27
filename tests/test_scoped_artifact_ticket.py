import hashlib

import pytest

from investment_evidence_engine.scoped_artifact_ticket import (
    authenticated_ticket_digest,
    issue_ticket,
    matches_observed_digest,
)

KEY = "synthetic-test-only"
DIGEST = hashlib.sha256(b"original bytes").hexdigest()
OTHER = hashlib.sha256(b"replacement bytes").hexdigest()
NOW = 1_800_000_000
SCOPE = "fixture-alpha"


def test_ticket_pre_auth_and_actual_bytes_separate():
    t = issue_ticket(SCOPE, KEY, DIGEST, ttl_seconds=120, now_ts=NOW)
    assert KEY not in t
    assert authenticated_ticket_digest(SCOPE, t, KEY, now_ts=NOW) == DIGEST
    assert matches_observed_digest(SCOPE, t, KEY, DIGEST, now_ts=NOW)
    assert not matches_observed_digest(SCOPE, t, KEY, OTHER, now_ts=NOW)
    assert not matches_observed_digest(SCOPE, t, KEY, "", now_ts=NOW)


def test_scope_token_and_mutated_digest_not_interchangeable():
    t = issue_ticket(SCOPE, KEY, DIGEST, ttl_seconds=300, now_ts=NOW)
    assert authenticated_ticket_digest("fixture-beta", t, KEY, now_ts=NOW) is None
    assert authenticated_ticket_digest(SCOPE, t, "different", now_ts=NOW) is None
    assert authenticated_ticket_digest(SCOPE, t.replace(DIGEST, OTHER), KEY, now_ts=NOW) is None
    assert authenticated_ticket_digest(SCOPE, t, KEY, now_ts=NOW+300) is None
    assert authenticated_ticket_digest(SCOPE, t, KEY, now_ts=NOW-1) is None


@pytest.mark.parametrize("ticket", [None, "", "1.deadbeef", "v2."+"1"*5000, "v2.invalid"])
def test_malformed_or_legacy_tickets_rejected(ticket):
    assert authenticated_ticket_digest(SCOPE, ticket, KEY, now_ts=NOW) is None


@pytest.mark.parametrize("ttl", [0, -1, 301, 10.5, True])
def test_ttl_bound(ttl):
    with pytest.raises(ValueError, match="TTL"):
        issue_ticket(SCOPE, KEY, DIGEST, ttl_seconds=ttl, now_ts=NOW)
