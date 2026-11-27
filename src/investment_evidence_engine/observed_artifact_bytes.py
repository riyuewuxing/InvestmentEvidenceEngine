"""Immutable observed-byte snapshots for read-only artifact delivery.

This helper verifies bytes and rejects changing local files. It is not a signature
verifier, multi-file filesystem transaction, or defense against a local admin.
It never writes or serves files, and carries no account or deployment data.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import stat
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_MAX_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_FILES = 10_000


@dataclass(frozen=True)
class ObservedFile:
    content: bytes
    sha256: str
    signature: tuple[int, int, int, int, int]


def _signature(st: os.stat_result) -> tuple[int, int, int, int, int]:
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def observe_file(
    path: Path,
    *,
    expected_sha256: str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> ObservedFile:
    """Read once, hash those bytes, and reject path replacement or mutation."""
    if max_bytes < 0:
        raise ValueError("ARTIFACT_BYTE_LIMIT")
    if expected_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("ARTIFACT_INVALID_DIGEST")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
        raise ValueError("ARTIFACT_NOT_REGULAR_OR_TOO_LARGE")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if _signature(before) != _signature(opened) or not stat.S_ISREG(opened.st_mode):
            raise ValueError("ARTIFACT_CHANGED")
        content = handle.read(max_bytes + 1)
        after = os.fstat(handle.fileno())
    if len(content) > max_bytes or len(content) != before.st_size:
        raise ValueError("ARTIFACT_SIZE_CHANGED_OR_LIMIT")
    if _signature(before) != _signature(after) or _signature(before) != _signature(path.lstat()):
        raise ValueError("ARTIFACT_CHANGED")
    digest = hashlib.sha256(content).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("ARTIFACT_DIGEST_MISMATCH")
    return ObservedFile(content, digest, _signature(before))


def observe_named_files(
    files: Mapping[str, Path], *, max_bytes: int = DEFAULT_MAX_BYTES,
) -> tuple[dict[str, ObservedFile], str]:
    """Bind exact parsed bytes to an ordered, domain-separated set identity.

    Detect changes across this bounded read window. This is not a filesystem
    transaction: no claim is made about coherence before or after the window.
    """
    if not files or len(files) > 128 or max_bytes < 0:
        raise ValueError("OBSERVATION_FILE_SET_LIMIT")
    if any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name)
           for name in files):
        raise ValueError("OBSERVATION_FILE_LABEL")
    if len({path.resolve() for path in files.values()}) != len(files):
        raise ValueError("OBSERVATION_FILE_DUPLICATE")
    digest = hashlib.sha256(b"OBSERVED_NAMED_FILE_SET_V1\0")
    records: dict[str, ObservedFile] = {}
    remaining = max_bytes
    for name, path in sorted(files.items()):
        item = observe_file(path, max_bytes=remaining)
        records[name] = item
        remaining -= len(item.content)
        digest.update(f"{name}:{len(item.content)}:{item.sha256}\n".encode("ascii"))
    if any(_signature(files[name].lstat()) != item.signature for name, item in records.items()):
        raise ValueError("OBSERVATION_FILE_SET_CHANGED")
    return records, digest.hexdigest()


def _inventory(root: Path, ignored: frozenset[str]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError("ARTIFACT_TREE_SYMLINK")
        if path.is_dir() or rel in ignored or path.name in {".DS_Store", "Thumbs.db"}:
            continue
        # ZIP entry names must not reinterpret Windows separators or drive prefixes.
        if "\\" in rel or ":" in rel or any(ord(char) < 32 for char in rel):
            raise ValueError("ARTIFACT_INVALID_MEMBER_NAME")
        if not path.is_file():
            raise ValueError("ARTIFACT_TREE_NON_REGULAR")
        found[rel] = path
    return dict(sorted(found.items()))


def observe_directory_zip(
    root: Path,
    *,
    required: str,
    ignored: frozenset[str] = frozenset(),
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
) -> tuple[dict, bytes] | None:
    """Hash and ZIP identical observed member bytes; reject detected tree changes."""
    if root.is_symlink():
        raise ValueError("ARTIFACT_TREE_SYMLINK")
    if not root.is_dir():
        return None
    files = _inventory(root, ignored)
    if required not in files:
        return None
    if len(files) > max_files:
        raise ValueError("ARTIFACT_FILE_LIMIT")
    total = 0
    latest_ns = 0
    digest = hashlib.sha256()
    signatures = {}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for rel, path in files.items():
            observed = observe_file(path, max_bytes=max_bytes - total)
            content = observed.content
            signatures[rel] = observed.signature
            latest_ns = max(latest_ns, observed.signature[3])
            total += len(content)
            digest.update(f"{rel}:{len(content)}:{observed.sha256}\n".encode())
            info = zipfile.ZipInfo(filename=rel, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    current = _inventory(root, ignored)
    if current.keys() != files.keys() or any(
        _signature(path.lstat()) != signatures[rel] for rel, path in current.items()
    ):
        raise ValueError("ARTIFACT_TREE_CHANGED")
    archive_bytes = buf.getvalue()
    sha = digest.hexdigest()
    return {
        "bundle_version": sha[:12],
        "bundle_sha256": sha,
        "file_count": len(files),
        "total_bytes": total,
        "generated_at": datetime.fromtimestamp(latest_ns / 1e9, tz=UTC).isoformat(),
        "zip_sha256": hashlib.sha256(archive_bytes).hexdigest(),
        "zip_bytes": len(archive_bytes),
    }, archive_bytes
