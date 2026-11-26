"""Public, deterministic transport checks. Integrity is not semantic or PIT admission."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

_STATUSES = ("ERROR", "BLOCK", "PENDING", "WARN", "PASS")
_METADATA = frozenset({"execution_request.json", "execution_result.json", "run_manifest.json"})
_OPERATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}")


def safe_operation_id(value: object) -> bool:
    return (isinstance(value, str) and _OPERATION_ID.fullmatch(value) is not None
            and value.lower() not in {"execution_request", "execution_result", "run_manifest"})


def safe_artifact_path(value: object) -> bool:
    """Portable relative output path, never metadata, drive names or path aliases."""
    if not isinstance(value, str) or len(value) > 1024:
        return False
    parts = value.split("/")
    return (all(_COMPONENT.fullmatch(part) is not None and not part.endswith(".")
                and part.split(".")[0].upper() not in {
                    "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                    *(f"LPT{i}" for i in range(1, 10)),
                } for part in parts)
            and parts[-1].lower() not in _METADATA)


def request_chain_errors(operations: Sequence[Mapping]) -> list[str]:
    errors = []
    prior = set()
    folded = set()
    for op in operations:
        op_id = op.get("operation_id")
        if not safe_operation_id(op_id):
            errors.append("UNSAFE_OPERATION_ID")
            continue
        if op_id.lower() in folded:
            errors.append("DUPLICATE_OPERATION_ID:" + op_id)
        params = op.get("parameters", {})
        deps = params.get("depends_on_operation_ids", []) if isinstance(params, Mapping) else None
        if (not isinstance(deps, list) or any(not isinstance(dep, str) or dep not in prior for dep in deps)
                or len(deps) != len(set(deps))):
            errors.append("INVALID_OPERATION_DEPENDENCIES:" + op_id)
        prior.add(op_id)
        folded.add(op_id.lower())
    return errors


def result_transport_errors(request_ops: Sequence[Mapping], result_ops: Sequence[Mapping],
                            overall_status: str) -> list[str]:
    """Require consistent sealed operation graph and portable, nonaliasing outputs.

    A successful dependency may be internal and produce no file; at least one output
    must exist for a usable packet. Historical absent exit codes are not fabricated.
    """
    errors = request_chain_errors(request_ops)
    wanted = [op.get("operation_id") for op in request_ops]
    actual = [op.get("operation_id") for op in result_ops]
    if wanted != actual:
        errors.append("OPERATION_ORDER_OR_COVERAGE_MISMATCH")
        return errors
    paths = set()
    status_by_id = {}
    for requested, result in zip(request_ops, result_ops):
        op_id = result["operation_id"]
        status = result.get("status")
        if status not in _STATUSES:
            errors.append("INVALID_OPERATION_STATUS:" + str(op_id))
            continue
        exit_code = result.get("exit_code")
        if status in {"PASS", "WARN"} and (exit_code not in (None, 0) or result.get("errors")):
            errors.append("SUCCESS_STATUS_CONFLICT:" + op_id)
        params = requested.get("parameters", {})
        deps = params.get("depends_on_operation_ids", []) if isinstance(params, Mapping) else []
        if isinstance(deps, list) and all(isinstance(dep, str) for dep in deps):
            upstream = [status_by_id.get(dep) for dep in deps]
            if status in {"PASS", "WARN"} and any(v not in {"PASS", "WARN"} for v in upstream):
                errors.append("UNUSABLE_UPSTREAM_PROMOTED:" + op_id)
            elif status == "PASS" and "WARN" in upstream:
                errors.append("UPSTREAM_WARNING_LOST:" + op_id)
        status_by_id[op_id] = status
        for artifact in result.get("artifacts", []):
            path = artifact.get("path")
            if not safe_artifact_path(path):
                errors.append("UNSAFE_ARTIFACT_PATH")
                continue
            folded = path.lower()
            if folded in paths or any(folded.startswith(other + "/") or other.startswith(folded + "/")
                                      for other in paths):
                errors.append("DUPLICATE_OR_ALIASED_ARTIFACT_PATH:" + path)
            paths.add(folded)
    statuses = set(status_by_id.values())
    expected = next((status for status in _STATUSES if status in statuses), None)
    if expected != overall_status:
        errors.append("OVERALL_STATUS_MISMATCH")
    if overall_status in {"PASS", "WARN"} and not paths:
        errors.append("NO_OBSERVABLE_ARTIFACTS")
    return errors


MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_CONTRACT_BYTES = 4 * 1024 * 1024


def read_contract_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_CONTRACT_BYTES:
        raise ValueError("CONTRACT_FILE_INVALID_OR_OVERSIZED")
    with path.open("rb") as handle:
        raw = handle.read(MAX_CONTRACT_BYTES + 1)
    if not raw or len(raw) > MAX_CONTRACT_BYTES:
        raise ValueError("CONTRACT_FILE_INVALID_OR_OVERSIZED")
    return raw


def observe_artifact_file(root: Path, relative: str, expected_size: int | None = None,
                          *, max_bytes: int = MAX_ARTIFACT_BYTES) -> tuple[str, int]:
    """Bounded rehash of a regular artifact below root, not a trust/authority assertion.

    The consumer owns the extraction directory; concurrent hostile filesystem mutation
    is outside this portable check's threat model.
    """
    if not safe_artifact_path(relative):
        raise ValueError("UNSAFE_ARTIFACT_PATH")
    if type(max_bytes) is not int or not 0 < max_bytes <= MAX_ARTIFACT_BYTES:
        raise ValueError("INVALID_ARTIFACT_LIMIT")
    if expected_size is not None and (type(expected_size) is not int or not 0 <= expected_size <= max_bytes):
        raise ValueError("ARTIFACT_SIZE_INVALID_OR_OVERSIZED")
    root = root.resolve()
    candidate = root
    for part in relative.split("/"):
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("ARTIFACT_SYMLINK_FORBIDDEN")
    if not candidate.resolve().is_relative_to(root) or not candidate.is_file():
        raise ValueError("ARTIFACT_NOT_OBSERVED")
    size = candidate.stat().st_size
    if size > max_bytes or (expected_size is not None and size != expected_size):
        raise ValueError("ARTIFACT_SIZE_MISMATCH_OR_OVERSIZED")
    digest = hashlib.sha256()
    count = 0
    with candidate.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            count += len(chunk)
            if count > max_bytes or count > size:
                raise ValueError("ARTIFACT_SIZE_CHANGED_OR_OVERSIZED")
            digest.update(chunk)
    if count != size or (expected_size is not None and count != expected_size):
        raise ValueError("ARTIFACT_SIZE_CHANGED_OR_OVERSIZED")
    return digest.hexdigest(), count


def read_verified_artifact(root: Path, relative: str, expected_sha256: str,
                           expected_size: int, *, max_bytes: int = MAX_CONTRACT_BYTES) -> bytes:
    """Return the same bounded bytes that were hashed, for subsequent parsing.

    Like observe_artifact_file, assumes a consumer-owned extraction directory.
    A hostile concurrent filesystem writer is not part of this portable threat
    model. No second unverified read is necessary to parse the returned bytes.
    """
    if not safe_artifact_path(relative):
        raise ValueError("UNSAFE_ARTIFACT_PATH")
    if (type(max_bytes) is not int or not 0 < max_bytes <= MAX_CONTRACT_BYTES
            or type(expected_size) is not int or not 0 < expected_size <= max_bytes):
        raise ValueError("ARTIFACT_SIZE_INVALID_OR_OVERSIZED")
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("ARTIFACT_DIGEST_INVALID")
    root = root.resolve()
    candidate = root
    for part in relative.split("/"):
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("ARTIFACT_SYMLINK_FORBIDDEN")
    if not candidate.resolve().is_relative_to(root) or not candidate.is_file():
        raise ValueError("ARTIFACT_NOT_OBSERVED")
    if candidate.stat().st_size != expected_size:
        raise ValueError("ARTIFACT_SIZE_MISMATCH_OR_OVERSIZED")
    with candidate.open("rb") as handle:
        raw = handle.read(expected_size + 1)
    if len(raw) != expected_size or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("ARTIFACT_HASH_OR_SIZE_MISMATCH")
    return raw
