import sys
from datetime import UTC, datetime
from pathlib import Path

from investment_evidence_engine.evidence_time_guard import source_visible

# Import the fixed-source validator without running its network entry point.

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from public_bls_archive_retention import SHA, SIZE, validate_archive  # noqa: E402


def test_retained_archive_actual_bytes_offline():
    raw = (Path(__file__).resolve().parents[1] / "public-evidence" / "sha256" / f"{SHA}.pdf").read_bytes()
    assert len(raw) == SIZE
    assert validate_archive(raw)["august_change_jobs"] == 22000


def test_original_bytes_not_historical_availability():
    release = datetime.fromisoformat("2025-09-05T08:30:00-04:00")
    captured = datetime.fromisoformat("2026-11-26T12:33:06.001861+00:00")
    assert not source_visible(available_at=release, retrieved_at=captured,
                              published_at=release, cutoff=datetime(2025, 9, 6, tzinfo=UTC))
    assert source_visible(available_at=captured, retrieved_at=captured,
                          published_at=release, cutoff=captured)
