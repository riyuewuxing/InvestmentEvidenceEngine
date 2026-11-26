"""Strict exact-pin inventory for the isolated public dependency control."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


def main() -> int:
    out = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--exclude-editable"],
        check=True, capture_output=True, text=True, timeout=30,
    ).stdout
    pins = [line.strip() for line in out.splitlines() if line.strip()]
    if not pins or any(not re.fullmatch(r"[A-Za-z0-9_.-]+==[^\s=]+", p) for p in pins):
        raise ValueError("EXACT_PIN_INVENTORY_REQUIRED")
    raw = ("\n".join(sorted(pins, key=str.casefold)) + "\n").encode()
    Path("public_docling_requirements.txt").write_bytes(raw)
    print("PUBLIC_DOCLING_DEPENDENCY_INVENTORY " + json.dumps({
        "package_count": len(pins), "sha256": hashlib.sha256(raw).hexdigest(),
        "scope": "ISOLATED_PUBLIC_CONTROL_ONLY", "private_dependency_environment_verified": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
