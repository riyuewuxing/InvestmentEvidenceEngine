"""Portable execution contract synchronized with touzizhuanjia execution_contract v1."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

OperationKind = Literal[
    "MARKET_DATA",
    "PRICE_ANALYTICS",
    "KLINE_RENDER",
    "COMPANY_EVENT_TIMELINE",
    "FUNDAMENTAL_HISTORY",
    "VALUATION_HISTORY",
    "OWNERSHIP_FLOW",
    "INDUSTRY_MACRO",
    "OFFICIAL_SOURCE",
    "PIT_REPLAY",
    "FACTOR_COMPUTE",
    "BACKTEST",
    "OPPORTUNITY_SCAN",
    "PORTFOLIO_MATH",
    "TEST_SUITE",
]
ExecutionStatus = Literal["PASS", "WARN", "BLOCK", "ERROR", "PENDING"]

_PRIVATE_PARAMETER_KEYS = {
    "account",
    "account_state",
    "portfolio_id",
    "holdings",
    "positions",
    "transactions",
    "cost_basis",
    "average_cost",
    "average_cost_or_cost_range",
    "available_cash",
    "cash_balance",
    "broker_account",
    "private_context",
}
_PRIVATE_REF_PREFIXES = ("private:", "account:", "portfolio:", "transaction:")


def canonical_sha256(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _find_private_parameter(value: object, path: str = "parameters") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            child_path = f"{path}.{key}"
            if normalized in _PRIVATE_PARAMETER_KEYS or normalized.startswith("private_"):
                return child_path
            found = _find_private_parameter(child, child_path)
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _find_private_parameter(child, f"{path}[{index}]")
            if found:
                return found
    return None


class ExecutionOperation(BaseModel):
    operation_id: str
    kind: OperationKind
    parameters: dict[str, object] = Field(default_factory=dict)
    expected_outputs: list[str] = Field(default_factory=list)
    evidence_domains: list[str] = Field(default_factory=list)
    public_data_only: Literal[True] = True
    decision_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_public_boundary(self) -> ExecutionOperation:
        if not self.operation_id.strip():
            raise ValueError("operation_id must not be empty")
        private_path = _find_private_parameter(self.parameters)
        if private_path:
            raise ValueError(f"private-state boundary violation: {private_path}")
        return self


class ExecutionRequest(BaseModel):
    schema_version: str = "1.0"
    job_id: str
    trace_id: str
    subject_repo: str
    subject_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    as_of: str
    operations: list[ExecutionOperation]
    input_refs: list[str] = Field(default_factory=list)
    private_data_included: Literal[False] = False
    decision_authority: Literal[False] = False
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    request_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_request(self) -> ExecutionRequest:
        if not self.operations:
            raise ValueError("execution request requires at least one operation")
        ids = [item.operation_id for item in self.operations]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate operation_id")
        if any(ref.strip().lower().startswith(_PRIVATE_REF_PREFIXES) for ref in self.input_refs):
            raise ValueError("private input refs are forbidden")
        return self

    def payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"request_sha256"})

    def compute_hash(self) -> str:
        return canonical_sha256(self.payload())

    def verify(self) -> bool:
        return bool(self.request_sha256) and self.request_sha256 == self.compute_hash()


class ExecutorStamp(BaseModel):
    repo: str
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    environment: dict[str, str] = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ArtifactRef(BaseModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)


class OperationResult(BaseModel):
    operation_id: str
    status: ExecutionStatus
    exit_code: int | None = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    metrics: dict[str, object] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    decision_authority: Literal[False] = False


class ExecutionResult(BaseModel):
    schema_version: str = "1.0"
    job_id: str
    trace_id: str
    subject_repo: str
    subject_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    executor: ExecutorStamp
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: ExecutionStatus
    operations: list[OperationResult] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    decision_authority: Literal[False] = False
    result_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    def payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"result_sha256"})

    def compute_hash(self) -> str:
        return canonical_sha256(self.payload())

    def seal(self) -> ExecutionResult:
        self.result_sha256 = self.compute_hash()
        return self
