"""Contract tests for exact dependency audit coverage validation."""
import hashlib
import json

import pytest

from investment_evidence_engine.dependency_audit import missing_pins, parse_pins, verify_audit


def payload(rows):
    return json.dumps({"dependencies": rows, "fixes": []}).encode()


def row(name="Example_pkg", version="1.0", vulns=None):
    return {"name": name, "version": version, "vulns": [] if vulns is None else vulns}


def test_exact_pin_audit_receipt():
    receipt = verify_audit(b"example-pkg==1.0\n", payload([row()]))
    assert receipt["package_count"] == 1
    assert len(receipt["audit_sha256"]) == 64
    assert receipt["audit_sha256"] == hashlib.sha256(payload([row()])).hexdigest()
    assert receipt["inventory_sha256"] == hashlib.sha256(b"example-pkg==1.0\n").hexdigest()


@pytest.mark.parametrize("rows", [
    [],
    [row(version="2.0")],
    [row(), row()],
    [row(vulns=[{"id": "example"}])],
    [{"name": "Example_pkg", "skip_reason": "unknown"}],
    [row(), row(name="extra")],
])
def test_audit_rejects_incomplete_or_unsafe_results(rows):
    with pytest.raises(ValueError):
        verify_audit(b"example-pkg==1.0\n", payload(rows))


def test_rejects_duplicate_inventory():
    with pytest.raises(ValueError):
        verify_audit(b"example-pkg==1.0\nExample_pkg==1.0\n", payload([row()]))


def test_explicit_supplement_covers_only_missing_pin():
    inventory = b"example-pkg==1.0\npackaging==26.4\n"
    primary = payload([row()])
    assert missing_pins(inventory, primary) == b"packaging==26.4\n"
    receipt = verify_audit(inventory, primary, payload([row("packaging", "26.4")]))
    assert receipt["package_count"] == 2
    assert receipt["supplemental_package_count"] == 1
    assert len(receipt["supplemental_audit_sha256"]) == 64


@pytest.mark.parametrize("rows", [
    [],
    [row("packaging", "26.3")],
    [row("packaging", "26.4"), row()],
    [row("packaging", "26.4", [{"id": "example"}])],
])
def test_supplement_cannot_hide_coverage_failure(rows):
    with pytest.raises(ValueError):
        verify_audit(
            b"example-pkg==1.0\npackaging==26.4\n",
            payload([row()]),
            payload(rows),
        )


@pytest.mark.parametrize("inventory", [
    b"",
    b"invalid==1.0==2.0\n",
    b"pkg @ https://example.invalid/pkg.whl\n",
    b"pkg==1.0 # comment\n",
])
def test_invalid_inventory_rejected(inventory):
    with pytest.raises(ValueError):
        parse_pins(inventory)


@pytest.mark.parametrize("audit", [
    b"not-json",
    b"[]",
    b'{"dependencies":[]}',
    b'{"dependencies":[],"fixes":[{}]}',
])
def test_invalid_audit_rejected(audit):
    with pytest.raises(ValueError):
        verify_audit(b"example-pkg==1.0\n", audit)
