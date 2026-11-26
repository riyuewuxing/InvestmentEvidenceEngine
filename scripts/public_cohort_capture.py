"""Opt-in public runner entrypoint. No cron and no private inputs."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from investment_evidence_engine.prospective_capture import (
    activation_path,
    canonical_bytes,
    collect,
    receipt_sha256,
    validate_marker,
)
from investment_evidence_engine.prospective_protocol import CohortProtocol

REPO = "riyuewuxing/InvestmentEvidenceEngine"
PROTOCOL = Path("pilot-protocols/public-daily-20261130-v1.json")
PROTOCOL_BLOB = "c74bbd3fead2b7016bc64fb38c424677ba312042"


def git(*args: str) -> bytes:
    proc = subprocess.run(["git", *args], capture_output=True, check=True, timeout=5)
    if len(proc.stdout) > 4096:
        raise ValueError("COHORT_GIT_OUTPUT_LIMIT")
    return proc.stdout


def main() -> int:
    try:
        if (os.environ.get("GITHUB_REPOSITORY") != REPO
                or os.environ.get("GITHUB_REF") != "refs/heads/main"
                or os.environ.get("GITHUB_RUN_ATTEMPT") != "1"):
            raise ValueError("COHORT_RUN_CONTEXT")
        before, head = os.environ["BEFORE_SHA"], os.environ["GITHUB_SHA"]
        if any(not re.fullmatch(r"[a-f0-9]{40}", sha) for sha in (before, head)):
            raise ValueError("COHORT_GIT_SHA")
        if git("rev-parse", "HEAD").decode().strip() != head:
            raise ValueError("COHORT_HEAD_MISMATCH")
        if git("rev-parse", "HEAD^").decode().strip() != before:
            raise ValueError("COHORT_NOT_SINGLE_COMMIT")
        if git("hash-object", str(PROTOCOL)).decode().strip() != PROTOCOL_BLOB:
            raise ValueError("COHORT_PROTOCOL_BLOB_MISMATCH")
        protocol = CohortProtocol.model_validate_json(PROTOCOL.read_bytes())
        path, phase, target = activation_path(protocol, git("diff", "--name-status", "-z", before, head))
        marker = Path(path)
        if marker.is_symlink() or not marker.is_file() or marker.stat().st_size > 256:
            raise ValueError("COHORT_MARKER_FILE")
        validate_marker(protocol, phase, target, marker.read_bytes())
        receipt = collect(protocol, target, phase)
    except Exception as exc:
        print("PUBLIC_COHORT_BLOCKED " + type(exc).__name__)
        return 2
    print("PUBLIC_COHORT_RECEIPT " + canonical_bytes(receipt).decode("utf-8"))
    print("PUBLIC_COHORT_SHA256 " + receipt_sha256(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
