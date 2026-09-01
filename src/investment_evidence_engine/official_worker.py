from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contracts import ArtifactRef, ExecutionOperation, OperationResult
from .sources import (
    DEFAULT_OFFICIAL_SOURCES,
    fetch_official_spec,
    normalized_document_text,
)
from .workers import WorkerContext


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _artifact(path: Path) -> ArtifactRef:
    return ArtifactRef(
        path=path.name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        media_type="application/json",
        size_bytes=path.stat().st_size,
    )


def run_official_source_resilient(
    operation: ExecutionOperation,
    context: WorkerContext,
) -> OperationResult:
    requested = operation.parameters.get("source_ids")
    source_ids = (
        [str(item) for item in requested]
        if isinstance(requested, list) and requested
        else list(DEFAULT_OFFICIAL_SOURCES)
    )
    checks: list[dict[str, object]] = []
    overall = "PASS"
    warnings: list[str] = []

    for source_id in source_ids:
        spec = DEFAULT_OFFICIAL_SOURCES.get(source_id)
        if spec is None:
            checks.append({"source_id": source_id, "status": "BLOCK", "error": "UNKNOWN_SOURCE_ID"})
            overall = "BLOCK"
            continue
        try:
            fetched, prior_failures = fetch_official_spec(spec)
            normalized = normalized_document_text(fetched.text)
            missing = [
                token for token in spec.expected_tokens
                if normalized_document_text(token) not in normalized
            ]
            source_status = "PASS" if not missing else "BLOCK"
            if source_status == "BLOCK":
                overall = "BLOCK"
            elif prior_failures and overall == "PASS":
                overall = "WARN"
            if prior_failures:
                warnings.append(f"OFFICIAL_SOURCE_FALLBACK_USED:{source_id}")
            checks.append(
                {
                    "source_id": source_id,
                    "status": source_status,
                    "resolved_url": fetched.url,
                    "primary_url": spec.url,
                    "fallback_failures": prior_failures,
                    "content_type": fetched.content_type,
                    "expected_tokens": list(spec.expected_tokens),
                    "missing_tokens": missing,
                    "content_sha256": fetched.content_sha256,
                }
            )
        except Exception as exc:  # noqa: BLE001 - official-source boundary
            checks.append(
                {
                    "source_id": source_id,
                    "status": "BLOCK",
                    "primary_url": spec.url,
                    "fallback_urls": list(spec.fallback_urls),
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )
            overall = "BLOCK"

    payload = {
        "as_of": str(operation.parameters.get("as_of") or ""),
        "checks": checks,
        "warnings": warnings,
        "decision_authority": False,
    }
    context.payloads[operation.operation_id] = payload
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    errors = [
        str(item.get("error") or f"MISSING_TOKENS:{','.join(item.get('missing_tokens') or [])}")
        for item in checks
        if item.get("status") == "BLOCK"
    ]
    return OperationResult(
        operation_id=operation.operation_id,
        status=overall,
        exit_code=0 if overall != "BLOCK" else 2,
        artifacts=[_artifact(path)],
        metrics={"source_count": len(checks), "pass_count": sum(item.get("status") == "PASS" for item in checks)},
        warnings=warnings,
        errors=errors,
    )
