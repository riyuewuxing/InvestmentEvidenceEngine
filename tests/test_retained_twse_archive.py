"""Reopen exact retained TWSE bytes; no network or historical-capture assertion."""
import hashlib
import importlib.util
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DIGEST = "0e6a2cbfb78befd2c77415e57aadfdf7acc1038a48e9d815bedb113730b622f2"
OBSERVED = datetime.fromisoformat("2026-11-26T14:02:28.910547+00:00")


def test_exact_retained_twse_original():
    spec = importlib.util.spec_from_file_location("twse_archive_retention",
        ROOT / "scripts/public_twse_archive_retention.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = ROOT / "public-evidence" / "sha256" / (DIGEST + ".csv")
    assert not path.is_symlink() and path.stat().st_size == 207911
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == DIGEST
    fields = module.verify_snapshot(raw, OBSERVED)
    assert fields["source_rows_observed"] == 1091
    assert fields["amounts"][0] == 586890319
    assert not fields["historical_vintage_verified"]
    with pytest.raises(ValueError, match="EXACT_VERSION_MISMATCH"):
        module.verify_snapshot(raw[:-1] + bytes([raw[-1] ^ 1]), OBSERVED)
