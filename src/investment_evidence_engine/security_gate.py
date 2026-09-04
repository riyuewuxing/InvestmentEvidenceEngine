"""Semantic triage for high-entropy findings in sealed public execution requests."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .contracts import ExecutionRequest

_ALLOWED_DETECTOR = "Hex High Entropy String"
_SEALED_FIELDS = {
    "subject_commit": re.compile(r'^\s*"subject_commit"\s*:\s*"([0-9a-f]{40})"\s*,?\s*$'),
    "request_sha256": re.compile(r'^\s*"request_sha256"\s*:\s*"([0-9a-f]{64})"\s*,?\s*$'),
}


def _relative_filename(filename: object, repo_root: Path) -> str | None:
    if not isinstance(filename, str) or not filename.strip():
        return None
    normalized = filename.replace("\\", "/")
    root = repo_root.resolve()
    candidate = Path(normalized)
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve().relative_to(root)
        except ValueError:
            return None
    else:
        candidate = Path(*[part for part in normalized.split("/") if part not in ("", ".")])
    if not candidate.parts or ".." in candidate.parts:
        return None
    return candidate.as_posix()


def _summary(finding: dict[str, Any], *, reason: str, filename: str | None = None, field: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "filename": filename or finding.get("filename", "<unknown>"),
        "line_number": finding.get("line_number"),
        "type": finding.get("type"),
        "reason": reason,
    }
    if field is not None:
        item["field"] = field
    return item


def _request_path_status(filename: str, repo_root: Path) -> tuple[Path | None, str | None]:
    relative = _relative_filename(filename, repo_root)
    if relative is None:
        return None, "non_request_path"
    path = Path(relative)
    is_request = len(path.parts) == 2 and path.parts[0] == "requests" and path.suffix == ".json"
    is_example_request = (
        len(path.parts) == 2 and path.parts[0] == "examples" and path.name.endswith(".request.json")
    )
    if not is_request and not is_example_request:
        return None, "non_request_path"
    return repo_root / path, None


def _triage_request_finding(
    finding: dict[str, Any],
    *,
    filename: str,
    request_path: Path,
    repo_root: Path,
) -> tuple[bool, dict[str, Any]]:
    if finding.get("type") != _ALLOWED_DETECTOR:
        return False, _summary(finding, reason="unsupported_detector", filename=filename)
    try:
        raw = request_path.read_text(encoding="utf-8")
        request = ExecutionRequest.model_validate_json(raw)
    except (OSError, UnicodeError, ValueError, TypeError):
        return False, _summary(finding, reason="request_not_sealed", filename=filename)
    if not request.verify():
        return False, _summary(finding, reason="request_not_sealed", filename=filename)

    line_number = finding.get("line_number")
    if isinstance(line_number, bool) or not isinstance(line_number, int):
        return False, _summary(finding, reason="invalid_line_number", filename=filename)
    lines = raw.splitlines()
    if line_number < 1 or line_number > len(lines):
        return False, _summary(finding, reason="line_not_found", filename=filename)
    line = lines[line_number - 1]
    matches = [(field, pattern, match) for field, pattern in _SEALED_FIELDS.items() if (match := pattern.fullmatch(line))]
    if len(matches) != 1:
        field_match = re.fullmatch(r'\s*"([^"\r\n]+)"\s*:\s*.*', line)
        field = field_match.group(1) if field_match else None
        return False, _summary(
            finding,
            reason="unsupported_request_field" if field else "line_not_sealed_identifier",
            filename=filename,
            field=field,
        )
    field, pattern, match = matches[0]
    if sum(1 for candidate_line in lines if pattern.fullmatch(candidate_line)) != 1:
        return False, _summary(finding, reason="duplicate_sealed_identifier", filename=filename, field=field)
    value = match.group(1)
    if value != getattr(request, field):
        return False, _summary(finding, reason="finding_value_mismatch", filename=filename, field=field)
    expected_hash = hashlib.sha1(value.encode("ascii")).hexdigest()
    if finding.get("hashed_secret") != expected_hash:
        return False, _summary(finding, reason="finding_hash_mismatch", filename=filename, field=field)
    return True, _summary(finding, reason="sealed_identifier", filename=filename, field=field)


def triage_detect_secrets(detect_secrets_path: Path, *, repo_root: Path = Path(".")) -> dict[str, Any]:
    """Return machine-readable triage without copying secret values into the report."""

    root = repo_root.resolve()
    try:
        payload = json.loads(detect_secrets_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"schema_version": 1, "status": "BLOCK", "secret_findings": 0, "ignored": [], "unexpected": [{"reason": "invalid_detect_secrets_report"}]}
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, dict):
        return {"schema_version": 1, "status": "BLOCK", "secret_findings": 0, "ignored": [], "unexpected": [{"reason": "invalid_detect_secrets_report"}]}

    ignored: list[dict[str, Any]] = []
    unexpected: list[dict[str, Any]] = []
    count = 0
    for result_filename, findings in results.items():
        if not isinstance(findings, list):
            unexpected.append({"filename": str(result_filename), "reason": "invalid_finding_list"})
            continue
        for finding in findings:
            count += 1
            if not isinstance(finding, dict):
                unexpected.append({"filename": str(result_filename), "reason": "invalid_finding"})
                continue
            filename = _relative_filename(finding.get("filename", result_filename), root)
            result_relative = _relative_filename(result_filename, root)
            if filename is None or result_relative != filename:
                unexpected.append(_summary(finding, reason="filename_mismatch", filename=filename or "<invalid>"))
                continue
            request_path, path_reason = _request_path_status(filename, root)
            if path_reason:
                unexpected.append(_summary(finding, reason=path_reason, filename=filename))
                continue
            assert request_path is not None
            accepted, item = _triage_request_finding(
                finding,
                filename=filename,
                request_path=request_path,
                repo_root=root,
            )
            (ignored if accepted else unexpected).append(item)
    return {
        "schema_version": 1,
        "status": "PASS" if not unexpected else "BLOCK",
        "secret_findings": count,
        "ignored": ignored,
        "unexpected": unexpected,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("detect_secrets", help="detect-secrets JSON report")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--report", default="security-triage.json")
    args = parser.parse_args(argv)
    report = triage_detect_secrets(Path(args.detect_secrets), repo_root=Path(args.repo_root))
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
