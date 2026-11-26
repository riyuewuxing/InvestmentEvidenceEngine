"""Verify exact public scan attachment bytes; no upstream/PIT admission authority."""
from __future__ import annotations

from pathlib import Path

from .contracts import InputArtifactRef, ObservedInputArtifact, canonical_sha256
from .scan_selection import select_scan_record
from .transport_integrity import read_verified_artifact


def observe_scan_input(root: Path, ref: InputArtifactRef) -> tuple[ObservedInputArtifact, bytes]:
    raw = read_verified_artifact(root, ref.materialized_path, ref.source_artifact_sha256,
                                 ref.source_artifact_size_bytes)
    digest, size = ref.source_artifact_sha256, len(raw)
    selected = select_scan_record(raw, ref.as_of)
    if selected["code"] != ref.selector.value or canonical_sha256(selected) != ref.selector.record_sha256:
        raise ValueError("INPUT_ARTIFACT_RECORD_SELECTOR_MISMATCH")
    observed = ObservedInputArtifact(input_id=ref.input_id, materialized_path=ref.materialized_path,
                                    observed_sha256=digest, observed_size_bytes=size, status="MATCH")
    return observed, raw
