"""Bounded JSON subprocess boundary for trusted local worker code.

The child receives a private temporary result path, not a pipe; noisy vendor
stdout/stderr cannot block the parent or become the result. No shell, no
retries, no background tasks. This supervises the direct child, not an
arbitrary subprocess tree; callers must not spawn unsupervised descendants.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_RESULT_BYTES = 16 * 1024 * 1024
MAX_TIMEOUT_SECONDS = 90.0
CLEANUP_SECONDS = 3.0


@dataclass(frozen=True)
class WorkerResult:
    status: str
    payload: dict[str, Any] | None = None
    exit_code: int | None = None
    elapsed_seconds: float = 0.0


def _reject_constant(value: str) -> None:
    raise ValueError("nonfinite JSON constant")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON key")
        out[key] = value
    return out


def write_worker_result(path: Path, payload: dict[str, Any], *, max_bytes: int = MAX_RESULT_BYTES) -> None:
    if not isinstance(payload, dict):
        raise ValueError("worker output must be an object")
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(data) > max_bytes:
        raise ValueError("worker result exceeds limit")
    staging = path.with_suffix(".part")
    with staging.open("xb") as out:
        out.write(data)
    os.replace(staging, path)


def run_json_worker(command: tuple[str, ...], *, timeout_seconds: float,
                    max_bytes: int = MAX_RESULT_BYTES) -> WorkerResult:
    if (not command or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in command)
            or isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS
            or isinstance(max_bytes, bool) or not isinstance(max_bytes, int)
            or not 0 < max_bytes <= MAX_RESULT_BYTES):
        raise ValueError("invalid worker limits or command")
    start = time.monotonic()

    def result(status: str, payload: dict | None = None, code: int | None = None) -> WorkerResult:
        return WorkerResult(status, payload, code, round(time.monotonic() - start, 3))

    with tempfile.TemporaryDirectory(prefix="bounded-json-") as folder:
        path = Path(folder) / "result.json"
        try:
            proc = subprocess.Popen(
                [*command, str(path)], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            return result("START_FAILED")
        try:
            remaining = max(0.0, timeout_seconds - (time.monotonic() - start))
            code = proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                if proc.poll() is None:
                    raise RuntimeError("worker termination failed")
            try:
                proc.wait(timeout=CLEANUP_SECONDS)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("worker termination unverified") from exc
            return result("WATCHDOG_TIMEOUT", code=proc.returncode)
        except BaseException:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=CLEANUP_SECONDS)
            raise
        if code != 0:
            return result("WORKER_FAILED", code=code)
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
                return result("RESULT_MISSING_OR_OVERSIZED", code=code)
            with path.open("rb") as handle:
                raw = handle.read(max_bytes + 1)
            if len(raw) > max_bytes:
                return result("RESULT_MISSING_OR_OVERSIZED", code=code)
            parsed = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant,
                                object_pairs_hook=_unique_object)
            if not isinstance(parsed, dict):
                return result("RESULT_INVALID", code=code)
            # Reject overflowed exponential literals as well as JSON constants.
            json.dumps(parsed, allow_nan=False)
        except (OSError, UnicodeError, ValueError, RecursionError):
            return result("RESULT_INVALID", code=code)
        return result("OK", parsed, code)
