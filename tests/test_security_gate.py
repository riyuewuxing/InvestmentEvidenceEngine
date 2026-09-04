import hashlib
import json
from pathlib import Path

from investment_evidence_engine.contracts import ExecutionOperation, ExecutionRequest
from investment_evidence_engine.security_gate import triage_detect_secrets


def _known_commit() -> str:
    return "".join(("c4525244", "b250042e", "360b3cd5", "5f3657ca", "89a1a5d6"))


def _sealed_request() -> ExecutionRequest:
    request = ExecutionRequest(
        job_id="job-security-test",
        trace_id="trace-security-test",
        subject_repo="riyuewuxing/touzizhuanjia",
        subject_commit=_known_commit(),
        as_of="2026-09-04",
        operations=[
            ExecutionOperation(
                operation_id="market-universe",
                kind="MARKET_UNIVERSE",
                parameters={"as_of": "2026-09-04", "market": "CN_A", "asset_type": "STOCK"},
            )
        ],
    )
    request.request_sha256 = request.compute_hash()
    return request


def _write_request(tmp_path: Path, request: ExecutionRequest | None = None) -> tuple[Path, dict[str, int]]:
    path = tmp_path / "requests" / "sealed.json"
    path.parent.mkdir()
    path.write_text(
        (request or _sealed_request()).model_dump_json(indent=2, exclude_none=False), encoding="utf-8"
    )
    lines = path.read_text(encoding="utf-8").splitlines()
    return path, {
        "subject_commit": next(i for i, line in enumerate(lines, 1) if '"subject_commit"' in line),
        "request_sha256": next(i for i, line in enumerate(lines, 1) if '"request_sha256"' in line),
        "job_id": next(i for i, line in enumerate(lines, 1) if '"job_id"' in line),
    }


def _finding(path: Path, line_number: int, value: str, *, detector_type: str = "Hex High Entropy String") -> dict:
    return {
        "type": detector_type,
        "filename": path.as_posix(),
        "hashed_secret": hashlib.sha1(value.encode()).hexdigest(),  # noqa: S324 - detector fixture
        "is_verified": False,
        "line_number": line_number,
    }


def _write_scan(tmp_path: Path, findings: list[dict]) -> Path:
    path = tmp_path / "detect-secrets.json"
    path.write_text(json.dumps({"results": {findings[0]["filename"]: findings}}), encoding="utf-8")
    return path


def test_triage_ignores_only_sealed_subject_and_request_hash_ids(tmp_path: Path) -> None:
    request_path, lines = _write_request(tmp_path)
    raw = request_path.read_text(encoding="utf-8").splitlines()
    subject = next(line.split('"')[3] for line in raw if '"subject_commit"' in line)
    request_hash = next(line.split('"')[3] for line in raw if '"request_sha256"' in line)
    scan = _write_scan(
        tmp_path,
        [
            _finding(request_path, lines["subject_commit"], subject),
            _finding(request_path, lines["request_sha256"], request_hash),
        ],
    )

    report = triage_detect_secrets(scan, repo_root=tmp_path)

    assert report["status"] == "PASS"
    assert report["secret_findings"] == 2
    assert len(report["ignored"]) == 2
    assert report["unexpected"] == []
    assert subject not in json.dumps(report)
    assert request_hash not in json.dumps(report)


def test_tampered_request_hash_is_not_ignored(tmp_path: Path) -> None:
    request_path, lines = _write_request(tmp_path)
    text = request_path.read_text(encoding="utf-8")
    original_hash = next(line.split('"')[3] for line in text.splitlines() if '"request_sha256"' in line)
    text = text.replace(original_hash, "0" * 64)
    request_path.write_text(text, encoding="utf-8")
    scan = _write_scan(tmp_path, [_finding(request_path, lines["request_sha256"], "0" * 64)])

    report = triage_detect_secrets(scan, repo_root=tmp_path)

    assert report["status"] == "BLOCK"
    assert report["ignored"] == []
    assert report["unexpected"][0]["reason"] == "request_not_sealed"


def test_unrelated_hex_field_in_valid_request_is_not_ignored(tmp_path: Path) -> None:
    request = _sealed_request()
    request.job_id = _known_commit()
    request.request_sha256 = request.compute_hash()
    request_path, lines = _write_request(tmp_path, request)
    scan = _write_scan(
        tmp_path,
        [_finding(request_path, lines["job_id"], _known_commit())],
    )

    report = triage_detect_secrets(scan, repo_root=tmp_path)

    assert report["status"] == "BLOCK"
    assert report["unexpected"][0]["reason"] == "unsupported_request_field"


def test_non_request_path_finding_is_not_ignored(tmp_path: Path) -> None:
    path = tmp_path / "src" / "token.py"
    path.parent.mkdir()
    value = _known_commit()
    path.write_text(f"TOKEN = '{value}'\n", encoding="utf-8")
    scan = _write_scan(tmp_path, [_finding(path, 1, value)])

    report = triage_detect_secrets(scan, repo_root=tmp_path)

    assert report["status"] == "BLOCK"
    assert report["unexpected"][0]["reason"] == "non_request_path"


def test_wrong_detector_type_is_not_ignored(tmp_path: Path) -> None:
    request_path, lines = _write_request(tmp_path)
    value = _known_commit()
    scan = _write_scan(
        tmp_path,
        [_finding(request_path, lines["subject_commit"], value, detector_type="Basic Auth Credentials")],
    )

    report = triage_detect_secrets(scan, repo_root=tmp_path)

    assert report["status"] == "BLOCK"
    assert report["unexpected"][0]["reason"] == "unsupported_detector"


def test_mismatched_finding_hash_is_not_ignored(tmp_path: Path) -> None:
    request_path, lines = _write_request(tmp_path)
    finding = _finding(request_path, lines["subject_commit"], _known_commit())
    finding["hashed_secret"] = "0" * 40
    scan = _write_scan(tmp_path, [finding])

    report = triage_detect_secrets(scan, repo_root=tmp_path)

    assert report["status"] == "BLOCK"
    assert report["unexpected"][0]["reason"] == "finding_hash_mismatch"
