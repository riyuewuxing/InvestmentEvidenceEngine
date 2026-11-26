"""Portable execution contract synchronized with touzizhuanjia execution_contract v1."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .transport_integrity import request_chain_errors, safe_artifact_path, safe_operation_id

OperationKind = Literal[
    "MARKET_DATA",
    "MARKET_UNIVERSE",
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
    "RESEARCH",
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
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    kind: OperationKind
    parameters: dict[str, object] = Field(default_factory=dict)
    expected_outputs: list[str] = Field(default_factory=list)
    evidence_domains: list[str] = Field(default_factory=list)
    public_data_only: Literal[True] = True
    decision_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_public_boundary(self) -> ExecutionOperation:
        if not safe_operation_id(self.operation_id):
            raise ValueError("unsafe or reserved operation_id")
        private_path = _find_private_parameter(self.parameters)
        if private_path:
            raise ValueError(f"private-state boundary violation: {private_path}")
        return self


class ArtifactRecordSelector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: Literal["code"]
    value: str = Field(pattern=r"^[0-9]{6}$")
    index: Literal[0]
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy: Literal["FIRST_RESEARCH_PRIORITY_RECORD_NOT_RETURN_FORECAST"]


class InputArtifactRef(BaseModel):
    """Transport identity only; declared upstream lineage is not independently admitted."""

    model_config = ConfigDict(extra="forbid")
    input_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    source_job_id: str
    source_trace_id: str
    source_subject_repo: str
    source_subject_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_executor_repo: str
    source_executor_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_operation_id: Literal["opportunity-scan"]
    source_artifact_path: Literal["opportunity-scan.json"]
    source_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_artifact_size_bytes: int = Field(strict=True, gt=0, le=4 * 1024 * 1024)
    materialized_path: str
    media_type: Literal["application/json"] = "application/json"
    as_of: str
    status: Literal["PASS", "WARN"]
    selector: ArtifactRecordSelector
    warnings: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    public_data_only: Literal[True] = True
    decision_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_location(self) -> InputArtifactRef:
        if (not safe_artifact_path(self.materialized_path)
                or not self.materialized_path.startswith("requests/inputs/")
                or not self.materialized_path.endswith(".json")):
            raise ValueError("INPUT_ARTIFACT_UNSAFE_MATERIALIZED_PATH")
        return self


class ObservedInputArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_id: str
    materialized_path: str
    observed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_size_bytes: int = Field(ge=0)
    status: Literal["MATCH", "BLOCK"]
    errors: list[str] = Field(default_factory=list)


class ExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    job_id: str
    trace_id: str
    subject_repo: str
    subject_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    as_of: str
    operations: list[ExecutionOperation]
    input_refs: list[str] = Field(default_factory=list)
    input_artifacts: list[InputArtifactRef] = Field(default_factory=list)
    private_data_included: Literal[False] = False
    decision_authority: Literal[False] = False
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    request_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_request(self) -> ExecutionRequest:
        if not self.operations:
            raise ValueError("execution request requires at least one operation")
        errors = request_chain_errors([item.model_dump(mode="json") for item in self.operations])
        if errors:
            raise ValueError(";".join(errors))
        if any(ref.strip().lower().startswith(_PRIVATE_REF_PREFIXES) for ref in self.input_refs):
            raise ValueError("private input refs are forbidden")
        if self.input_artifacts:
            if len(self.input_artifacts) != 1:
                raise ValueError("ONLY_ONE_PUBLIC_SCAN_INPUT_SUPPORTED")
            item = self.input_artifacts[0]
            if item.as_of != self.as_of or self.input_refs != [item.input_id]:
                raise ValueError("INPUT_ARTIFACT_REQUEST_SCOPE_MISMATCH")
            if [op.kind for op in self.operations] != ["MARKET_DATA", "RESEARCH"]:
                raise ValueError("INPUT_ARTIFACT_OPERATION_CHAIN_MISMATCH")
            market, research = self.operations
            if (market.parameters.get("subject_ids") != [item.selector.value]
                    or research.parameters.get("depends_on_operation_ids") != [market.operation_id]
                    or any(op.parameters.get("input_artifact_ids") != [item.input_id]
                           or op.parameters.get("as_of") != self.as_of for op in self.operations)):
                raise ValueError("INPUT_ARTIFACT_OPERATION_BINDING_MISMATCH")
        elif any("input_artifact_ids" in op.parameters or op.kind == "RESEARCH" for op in self.operations):
            raise ValueError("INPUT_ARTIFACT_REQUIRED")
        return self

    def payload(self) -> dict[str, object]:
        result = self.model_dump(mode="json", exclude={"request_sha256"})
        if not self.input_artifacts:
            result.pop("input_artifacts")
        return result

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
    as_of: str | None = None
    observed_input_artifacts: list[ObservedInputArtifact] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    decision_authority: Literal[False] = False
    result_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    def payload(self) -> dict[str, object]:
        result = self.model_dump(mode="json", exclude={"result_sha256", "as_of", "observed_input_artifacts"})
        if self.as_of is not None:
            result["as_of"] = self.as_of
        if self.observed_input_artifacts:
            result["observed_input_artifacts"] = [item.model_dump(mode="json") for item in self.observed_input_artifacts]
        return result

    def compute_hash(self) -> str:
        return canonical_sha256(self.payload())

    def seal(self) -> ExecutionResult:
        self.result_sha256 = self.compute_hash()
        return self
