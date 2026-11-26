"""Strict exact-pin inventory for the isolated public dependency control."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from investment_evidence_engine.dependency_audit import missing_pins, parse_pins, verify_audit


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
        receipt.update(scope="ISOLATED_PUBLIC_CONTROL_ONLY", private_dependency_environment_verified=False)
        print("PUBLIC_DOCLING_AUDIT_RECEIPT " + json.dumps(receipt, sort_keys=True))
        return 0
    if sys.argv[1:]:
        raise ValueError("UNKNOWN_ARGUMENT")
    out = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--exclude-editable"],
        check=True, capture_output=True, text=True, timeout=30,
    ).stdout
    pins = [line.strip() for line in out.splitlines() if line.strip()]
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
