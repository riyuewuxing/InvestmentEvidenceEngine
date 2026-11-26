import hashlib
import json

import pytest

from investment_evidence_engine.snapshot_integrity import (
    raw_snapshot_matches,
    verify_json_snapshot_fields,
)


def test_all_artifacts_are_required_and_independently_rehashed():
    bodies = {"ledger": b"original ledger", "graph": b"original graph", "gaps": b"original gaps"}
    expected = {k: hashlib.sha256(v).hexdigest() for k, v in bodies.items()}
    required = frozenset(bodies)
    assert raw_snapshot_matches(bodies, expected, required=required)
    for key in required:
        assert not raw_snapshot_matches(bodies | {key: b"changed"}, expected, required=required)
        assert not raw_snapshot_matches({k: v for k, v in bodies.items() if k != key},
                                        expected, required=required)
        assert not raw_snapshot_matches(bodies, expected | {key: "x"*64}, required=required)
    assert not raw_snapshot_matches({}, {}, required=frozenset())
    assert not raw_snapshot_matches(bodies, expected | {"extra": "a"*64}, required=required)


def test_runtime_json_snapshot_requires_actual_version_and_source():
    raw = b'{"status":"PASS","parser":{"version":"2","source":"abc"},"count":1}'
    digest = hashlib.sha256(raw).hexdigest()
    required = {("status",): "PASS", ("parser", "version"): "2", ("parser", "source"): "abc"}
    assert verify_json_snapshot_fields(raw, digest, required)["count"] == 1
    with pytest.raises(ValueError, match="REPORT_DIGEST_MISMATCH"):
        verify_json_snapshot_fields(raw + b" ", digest, required)
    # A new matching digest is not sufficient when claimed version differs.
    old = raw.replace(b'"version":"2"', b'"version":"1"')
    with pytest.raises(ValueError, match="REPORT_FIELD_MISMATCH:parser.version"):
        verify_json_snapshot_fields(old, hashlib.sha256(old).hexdigest(), required)
    with pytest.raises(ValueError, match="REPORT_FIELD_MISSING"):
        verify_json_snapshot_fields(raw, digest, {("parser", "unknown"): "abc"})
    with pytest.raises(ValueError, match="REPORT_FIELD_MISMATCH"):
        verify_json_snapshot_fields(raw, digest, {("count",): True})


@pytest.mark.parametrize("raw", [
    b'{"status":"PASS","status":"FAIL"}',
    b'{"status":"PASS","nested":{"x":0,"x":1}}',
    b'{"status":"PASS","number":NaN}',
    b'{"status":"PASS","number":Infinity}',
    b'["PASS"]',
    b'not-json',
])
def test_runtime_json_snapshot_rejects_ambiguous_documents(raw):
    with pytest.raises(ValueError):
        verify_json_snapshot_fields(raw, hashlib.sha256(raw).hexdigest(), {("status",): "PASS"})


def test_runtime_json_snapshot_no_vacuous_contract():
    raw = json.dumps({"status": "PASS"}).encode()
    digest = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="REPORT_FIELDS_REQUIRED"):
        verify_json_snapshot_fields(raw, digest, {})
    with pytest.raises(ValueError, match="REPORT_FIELD_PATH_INVALID"):
        verify_json_snapshot_fields(raw, digest, {(): "PASS"})
