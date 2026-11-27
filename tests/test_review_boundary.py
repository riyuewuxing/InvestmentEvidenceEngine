import hashlib
import json
from pathlib import Path

import pytest

from investment_evidence_engine.review_boundary import original_support_blocker, stock_review_scope

FIXTURE = Path(__file__).parents[1] / "fixtures/current_case/observed_000035_20261127.json"


def check(raw, source_class="OTHER"):
    return original_support_blocker(raw, source_class=source_class,
                                    expected_sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize(("subject", "route"), [
    ("000035", "sz000035"), ("sz000035", "sz000035"), ("600519", "sh600519"),
    ("sh600519", "sh600519"), ("302132", "sz302132"), ("920001", "bj920001"),
    ("000001", "sz000001"),
])
def test_stock_scope_route_only(subject, route):
    assert stock_review_scope(subject) == route


@pytest.mark.parametrize("subject", [
    "510300", "sh510300", "159915", "sz159915", "sh000001", "sz399001",
    "sz600519", "sh000035", "bj600519", "600519.SH", "not-a-code", "１２３４５６",
    None, 600519, "090000", "161907",
])
def test_stock_scope_rejects_conflicting_or_unmodeled_routes(subject):
    assert stock_review_scope(subject) is None


def test_actual_archive_and_every_original_receipt_are_metadata_only():
    raw = FIXTURE.read_bytes()
    assert check(raw, "RELABELLED_ORIGINAL") == "SUPPORT_METADATA_ONLY"
    fixture = json.loads(raw)
    for entry in fixture["receipts"].values():
        payload = entry["line"].split(" " + entry["marker"] + " ", 1)[1].encode()
        assert check(payload, "RELABELLED_ORIGINAL") == "SUPPORT_METADATA_ONLY"


@pytest.mark.parametrize("raw", [
    b'{"pit_safe":false}', b'{"admissible_for_decision":false}',
    b'{"pit_eligible":false}', b'{"source_class":"DYNAMIC_CARD_DECODED_INPUTS"}',
    b'[{"executor_commit":"test","raw_body_retained":false}]',
    b'{"executor_commit":"test","durable_original_bytes_verified":false}',
    b'\xef\xbb\xbf {"pit_safe":false}',
])
def test_negative_metadata_markers_cannot_be_overridden_by_matching_digest(raw):
    assert check(raw, "ORIGINAL") == "SUPPORT_METADATA_ONLY"


@pytest.mark.parametrize("raw", [
    b'{"pit_safe":false,"pit_safe":true}', b'{"value":NaN}', b'{"value":1e999}',
    b'{"scope":[]}', b'{"source_class":{}}',
])
def test_malformed_json_rejected(raw):
    assert check(raw) == "SUPPORT_JSON_INVALID"


def test_ordinary_non_authoritative_source_is_not_automatically_admitted_or_rejected():
    assert check(b'{"decision_authority":false,"raw_body_retained":true}') is None
    assert check(b'plain original text') is None
    assert check(b'plain text', "DYNAMIC_CARD_DECODED_INPUTS") == "SUPPORT_METADATA_ONLY"
    assert original_support_blocker(b"changed", source_class="ORIGINAL",
                                    expected_sha256="a" * 64) == "SUPPORT_BYTES_MISMATCH"
