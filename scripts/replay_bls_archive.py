"""Read actual retained BLS originals; distinguish published-version reconstruction from observation."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from public_bls_archive_retention import ARCHIVES, validate_archive

from investment_evidence_engine.revision_chain import Revision, revision_view

ROOT = Path(__file__).resolve().parents[1] / "public-evidence" / "sha256"
# Capture clocks from observed run logs. Durable verification clocks are
# successful actual-byte pytest observations, rounded up to microseconds,
# not the historical publication.
TIMES = {
    "202508": ("2026-11-26T12:33:06.001861+00:00", "2026-11-26T12:34:55.244063+00:00"),
    "202509": ("2026-11-26T12:35:35.442319+00:00", "2026-11-26T12:38:00.547308+00:00"),
    "202511": ("2026-11-26T12:35:42.932059+00:00", "2026-11-26T12:38:00.547308+00:00"),
}


def retained_revisions(root: Path = ROOT) -> tuple[Revision, ...]:
    rows = []
    for month, (digest, size, _, _, _, _) in ARCHIVES.items():
        path = root / (digest + ".pdf")
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
            raise ValueError("BLS_RETAINED_FILE_SCOPE")
        with path.open("rb") as handle:
            raw = handle.read(size + 1)
        fields = validate_archive(raw, month)
        previous = fields["previous_august_change_jobs"]
        observed, durable = (datetime.fromisoformat(s) for s in TIMES[month])
        rows.append(Revision(
            series_id="BLS_NONFARM_PAYROLL_MONTHLY_CHANGE_SA", period="2025-08",
            unit="JOBS", source_id="BLS_ARCHIVE_VIA_FRASER",
            revision_id=month, predecessor_id=rows[-1].revision_id if rows else None,
            value=Decimal(fields["august_change_jobs"]),
            predecessor_value=None if previous is None else Decimal(previous),
            declared_release_at=datetime.fromisoformat(fields["declared_release_at"]),
            observed_at=observed, durable_verified_at=durable, raw_sha256=fields["sha256"]))
    return tuple(rows)


def run_replay(now: datetime) -> dict:
    rows = retained_revisions()
    declared = [revision_view(rows, cutoff=datetime.fromisoformat(stamp), analysis_at=now,
                              mode="DECLARED_RELEASE_RECONSTRUCTION")
                for stamp in ("2025-09-05T08:29:59-04:00", "2025-09-05T08:30:00-04:00",
                              "2025-11-20T08:30:00-05:00", "2025-12-16T08:30:00-05:00")]
    observed = [revision_view(rows, cutoff=datetime.fromisoformat(stamp), analysis_at=now,
                              mode="DURABLE_OBSERVED_VIEW")
                for stamp in ("2025-12-16T08:30:00-05:00", "2026-11-26T12:34:55.244063+00:00",
                              "2026-11-26T12:38:00.547308+00:00")]
    return {"source": "BLS_ARCHIVE_VIA_FRASER", "actual_files_reopened_and_parsed": len(rows),
            "declared_release_views": declared, "durable_observed_views": observed,
            "decision_authority": False, "pit_safe": False}


if __name__ == "__main__":
    print("BLS_ARCHIVE_REPLAY " + json.dumps(run_replay(datetime.now(UTC)), sort_keys=True), flush=True)
