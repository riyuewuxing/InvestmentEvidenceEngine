"""Public, deterministic transport checks. Integrity is not semantic or PIT admission."""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

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
