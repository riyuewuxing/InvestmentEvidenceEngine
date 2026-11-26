import sys
from datetime import UTC, datetime
from pathlib import Path

from investment_evidence_engine.evidence_time_guard import source_visible

# Import the fixed-source validator without running its network entry point.

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from public_bls_archive_retention import ARCHIVES, SHA, SIZE, validate_archive  # noqa: E402


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


def test_retained_complete_revision_chain():
    root = Path(__file__).resolve().parents[1] / "public-evidence" / "sha256"
    results = []
    for month, (digest, size, pages, _, _, _) in ARCHIVES.items():
        raw = (root / f"{digest}.pdf").read_bytes()
        assert len(raw) == size
        result = validate_archive(raw, month)
        assert result["page_count"] == pages
        results.append(result)
    assert [r["august_change_jobs"] for r in results] == [22000, -4000, -26000]
    assert [r["previous_august_change_jobs"] for r in results] == [None, 22000, -4000]
    assert results[1]["october_release_not_published_observed"]
