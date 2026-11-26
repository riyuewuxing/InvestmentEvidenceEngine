"""Strict exact-pin inventory for the isolated public dependency control."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_pins(raw: bytes) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in raw.decode("utf-8").splitlines():
        if not re.fullmatch(r"[A-Za-z0-9_.-]+==[^\s=]+", line):
            raise ValueError("EXACT_PIN_INVENTORY_REQUIRED")
        name, version = line.split("==", 1)
        name = canonical_name(name)
        if name in pins:
            raise ValueError("DUPLICATE_PIN")
        pins[name] = version
    if not pins:
        raise ValueError("EMPTY_INVENTORY")
    return pins


def parse_audit(audit: bytes) -> dict[str, str]:
    report = json.loads(audit)
    if not isinstance(report, dict) or report.get("fixes") != []:
        raise ValueError("AUDIT_SCHEMA_OR_FIXES")
    records = report.get("dependencies")
    if not isinstance(records, list):
        raise ValueError("AUDIT_DEPENDENCIES_REQUIRED")
    observed: dict[str, str] = {}
    for row in records:
        if not isinstance(row, dict) or "skip_reason" in row or row.get("vulns") != []:
            raise ValueError("AUDIT_SKIPPED_OR_VULNERABLE")
        name, version = row.get("name"), row.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise ValueError("AUDIT_PIN_REQUIRED")
        name = canonical_name(name)
        if name in observed:
            raise ValueError("AUDIT_DUPLICATE")
        observed[name] = version
    return observed


def missing_pins(inventory: bytes, audit: bytes) -> bytes:
    expected, observed = parse_pins(inventory), parse_audit(audit)
    if any(expected.get(k) != v for k, v in observed.items()):
        raise ValueError("AUDIT_UNEXPECTED_PIN")
    missing = sorted(expected.keys() - observed.keys())
    return "".join(f"{name}=={expected[name]}\n" for name in missing).encode()


def verify_audit(
    inventory: bytes, audit: bytes, supplemental: bytes | None = None,
) -> dict[str, object]:
    expected, observed = parse_pins(inventory), parse_audit(audit)
    missing = missing_pins(inventory, audit)
    if supplemental is not None:
        if not missing or parse_audit(supplemental) != parse_pins(missing):
            raise ValueError("SUPPLEMENTAL_AUDIT_MISMATCH")
        observed.update(parse_audit(supplemental))
    if observed != expected:
        raise ValueError("AUDIT_INVENTORY_MISMATCH")
    return {
        "package_count": len(expected),
        "inventory_sha256": hashlib.sha256(inventory).hexdigest(),
        "audit_sha256": hashlib.sha256(audit).hexdigest(),
        "audit_bytes": len(audit),
        "primary_package_count": len(parse_audit(audit)),
        "supplemental_package_count": len(parse_pins(missing)) if missing else 0,
        "supplemental_audit_sha256": (
            hashlib.sha256(supplemental).hexdigest() if supplemental is not None else None
        ),
        "scope": "ISOLATED_PUBLIC_CONTROL_ONLY",
        "private_dependency_environment_verified": False,
    }


def main() -> int:
    if sys.argv[1:] == ["--find-missing"]:
        missing = missing_pins(
            Path("public_docling_requirements.txt").read_bytes(),
            Path("public_docling_audit.json").read_bytes(),
        )
        Path("public_docling_missing.txt").write_bytes(missing)
        print("PUBLIC_DOCLING_MISSING_PINS " + missing.decode().strip())
        return 0
    if sys.argv[1:] == ["--verify-audit"]:
        supplement = Path("public_docling_supplemental_audit.json")
        receipt = verify_audit(
            Path("public_docling_requirements.txt").read_bytes(),
            Path("public_docling_audit.json").read_bytes(),
            supplement.read_bytes() if supplement.is_file() else None,
        )
        print("PUBLIC_DOCLING_AUDIT_RECEIPT " + json.dumps(receipt, sort_keys=True))
        return 0
    if sys.argv[1:]:
        raise ValueError("UNKNOWN_ARGUMENT")
    out = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--exclude-editable"],
        check=True, capture_output=True, text=True, timeout=30,
    ).stdout
    pins = [line.strip() for line in out.splitlines() if line.strip()]
    if not pins or any(not re.fullmatch(r"[A-Za-z0-9_.-]+==[^\s=]+", p) for p in pins):
        raise ValueError("EXACT_PIN_INVENTORY_REQUIRED")
    raw = ("\n".join(sorted(pins, key=str.casefold)) + "\n").encode()
    parse_pins(raw)
    Path("public_docling_requirements.txt").write_bytes(raw)
    print("PUBLIC_DOCLING_DEPENDENCY_INVENTORY " + json.dumps({
        "package_count": len(pins), "sha256": hashlib.sha256(raw).hexdigest(),
        "scope": "ISOLATED_PUBLIC_CONTROL_ONLY", "private_dependency_environment_verified": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
