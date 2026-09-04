from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from .contracts import ExecutionRequest, ExecutionResult, ExecutorStamp
from .dispatch import run_operation
from .workers import WorkerContext

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "NOT_INSTALLED"


def _executor_identity(repo_arg: str | None, commit_arg: str | None) -> tuple[str, str]:
    repo = repo_arg or os.getenv("GITHUB_REPOSITORY") or "local/InvestmentEvidenceEngine"
    commit = commit_arg or os.getenv("GITHUB_SHA") or os.getenv("ENGINE_COMMIT")
    if commit is None or not _COMMIT_RE.fullmatch(commit):
        raise ValueError("executor commit must be supplied as a 40-character git SHA")
    return repo, commit


def _overall_status(statuses: list[str]) -> str:
    if any(status == "ERROR" for status in statuses):
        return "ERROR"
    if any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    if any(status == "PENDING" for status in statuses):
        return "PENDING"
    if any(status == "WARN" for status in statuses):
        return "WARN"
    return "PASS"


def execute_request(
    request_path: Path,
    *,
    output_dir: Path,
    executor_repo: str,
    executor_commit: str,
) -> ExecutionResult:
    request = ExecutionRequest.model_validate_json(request_path.read_text(encoding="utf-8"))
    if not request.verify():
        raise ValueError("ExecutionRequest request_sha256 is missing or invalid")

    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(request_path, output_dir / "execution_request.json")
    started = datetime.now(UTC)
    context = WorkerContext(output_dir=output_dir, request_as_of=request.as_of)
    results = [run_operation(operation, context) for operation in request.operations]
    finished = datetime.now(UTC)
    result = ExecutionResult(
        job_id=request.job_id,
        trace_id=request.trace_id,
        subject_repo=request.subject_repo,
        subject_commit=request.subject_commit,
        executor=ExecutorStamp(
            repo=executor_repo,
            commit=executor_commit,
            environment={
                "python": platform.python_version(),
                "platform": platform.platform(),
                "akshare": _version("akshare"),
                "baostock": _version("baostock"),
                "tushare": _version("tushare"),
                "pandas": _version("pandas"),
                "numpy": _version("numpy"),
                "mplfinance": _version("mplfinance"),
                "ruff": _version("ruff"),
                "pytest": _version("pytest"),
            },
            started_at=started,
            finished_at=finished,
        ),
        request_sha256=request.request_sha256,
        status=_overall_status([item.status for item in results]),
        operations=results,
    ).seal()
    (output_dir / "execution_result.json").write_text(
        result.model_dump_json(indent=2),
        encoding="utf-8",
    )
    manifest = {
        "job_id": result.job_id,
        "trace_id": result.trace_id,
        "subject_repo": result.subject_repo,
        "subject_commit": result.subject_commit,
        "executor_repo": result.executor.repo,
        "executor_commit": result.executor.commit,
        "request_sha256": result.request_sha256,
        "result_sha256": result.result_sha256,
        "status": result.status,
        "operation_statuses": {item.operation_id: item.status for item in result.operations},
        "artifacts": [
            artifact.model_dump(mode="json")
            for item in result.operations
            for artifact in item.artifacts
        ],
        "decision_authority": False,
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute one public InvestmentEvidenceEngine request")
    parser.add_argument("request", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("run-output"))
    parser.add_argument("--executor-repo")
    parser.add_argument("--executor-commit")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        repo, commit = _executor_identity(args.executor_repo, args.executor_commit)
        result = execute_request(
            args.request,
            output_dir=args.output_dir,
            executor_repo=repo,
            executor_commit=commit,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary must emit a structured fatal error.
        print(f"ENGINE_FATAL:{type(exc).__name__}:{exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(result.model_dump_json(indent=2))
    if result.status in {"BLOCK", "ERROR"}:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
