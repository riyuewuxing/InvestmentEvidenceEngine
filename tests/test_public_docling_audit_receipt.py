"""Contract tests for public audit receipt validation."""
import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "public_docling_inventory",
    Path(__file__).resolve().parents[1] / "scripts/public_docling_dependency_inventory.py",
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
verify_audit = _mod.verify_audit


def payload(rows):
    return json.dumps({"dependencies": rows, "fixes": []}).encode()


def row(name="Example_pkg", version="1.0", vulns=None):
    return {"name": name, "version": version, "vulns": [] if vulns is None else vulns}


def test_exact_pin_audit_receipt():
    receipt = verify_audit(b"example-pkg==1.0\n", payload([row()]))
    assert receipt["package_count"] == 1
    assert len(receipt["audit_sha256"]) == 64
    assert receipt["private_dependency_environment_verified"] is False


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
