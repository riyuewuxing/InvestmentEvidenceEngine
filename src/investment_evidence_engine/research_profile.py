"""Formal RESEARCH remains blocked; execute a separately marked diagnostic."""
from __future__ import annotations

from .contracts import ArtifactRef, ExecutionOperation, OperationResult
from .research_profile_evidence import FORMAL_BLOCKER, PROFILE, check_profile, evaluate_market_profile
from .snapshot_integrity import strict_json_loads
from .transport_integrity import read_verified_artifact
from .workers import WorkerContext, _artifact, _write_json


def run_research(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    params = operation.parameters
    ids = params.get("input_artifact_ids")
    ref = (context.input_artifacts.get(ids[0]) if isinstance(ids, list) and len(ids) == 1
           and isinstance(ids[0], str) else None)
    cutoff = params.get("as_of")
    attachment_scope = bool(ref is not None and isinstance(cutoff, str)
                            and ref.as_of == cutoff == context.request_as_of)
    deps = params.get("depends_on_operation_ids")
    dep = deps[0] if isinstance(deps, list) and len(deps) == 1 and isinstance(deps[0], str) else None
    provenance = context.completed_operations.get(dep, {}) if dep else {}
    payload = context.payloads.get(dep, {}) if dep else {}
    frame = context.frames.get(dep) if dep else None
    scoped_market = bool(attachment_scope and provenance.get("kind") == "MARKET_DATA"
                         and provenance.get("status") in {"PASS", "WARN"}
                         and provenance.get("as_of") == cutoff
                         and isinstance(payload, dict) and payload.get("as_of") == cutoff
                         and payload.get("symbol") == ref.selector.value
                         and frame is not None and not frame.empty)
    readiness = {
        "candidate_attachment": "CONTEXT_SCOPE_MATCH_TRANSPORT_ONLY" if attachment_scope else "UNVERIFIED",
        "market_input": "OBSERVED_SCOPE_MATCH_ONLY" if scoped_market else "UNVERIFIED",
        "profile_requested": params.get("profile") == PROFILE,
        "historical_source_vintage": "NOT_ADMITTED",
        "historical_listing_and_corporate_actions": "NOT_ADMITTED",
        "historical_execution_and_costs": "NOT_ADMITTED",
        "formal_profile": "NOT_ADMITTED",
        "private_source_graph": "NOT_VERIFIED_BY_PUBLIC_ENGINE",
        "research_admitted": False, "pit_safe": False,
        "decision_authority": False, "execution_allowed": False,
        "arithmetic_profile": "NOT_RUN",
    }
    artifacts = []
    if scoped_market and readiness["profile_requested"]:
        try:
            check_profile(params)
            refs = provenance.get("artifact_refs")
            if not isinstance(refs, list) or len(refs) != 1:
                raise ValueError("RESEARCH_MARKET_ARTIFACT_REQUIRED")
            market_ref = ArtifactRef.model_validate(refs[0])
            if market_ref.path != dep + ".json":
                raise ValueError("RESEARCH_MARKET_ARTIFACT_PATH")
            raw = read_verified_artifact(context.output_dir, market_ref.path,
                                         market_ref.sha256, market_ref.size_bytes)
            if strict_json_loads(raw) != payload:
                raise ValueError("RESEARCH_MARKET_ARTIFACT_CONTEXT_MISMATCH")
            # Read the retained scan attachment again; the result is bound to
            # exact candidate bytes, not to the unverified declared source graph.
            from .input_binding import observe_scan_input

            receipt, _ = observe_scan_input(context.output_dir, ref)
            report = evaluate_market_profile(raw, symbol=ref.selector.value, as_of=cutoff)
            report |= {"status": "BLOCK", "formal_blocker": FORMAL_BLOCKER,
                       "candidate_attachment_sha256": receipt.observed_sha256,
                       "candidate_record_sha256": ref.selector.record_sha256,
                       "source_operation_id": dep, "source_graph_verified": False,
                       "historical_selection_verified": False}
            path = context.output_dir / f"{operation.operation_id}.json"
            _write_json(path, report)
            artifacts = [_artifact(path, media_type="application/json")]
            readiness["arithmetic_profile"] = "EXECUTED_RETROSPECTIVE_ONLY"
            readiness["market_input"] = "EXACT_ARTIFACT_BYTES_AND_OBSERVED_SCOPE_MATCH"
        except (ValueError, TypeError, KeyError, OSError, RuntimeError, OverflowError) as exc:
            reason = str(exc)
            readiness["arithmetic_profile"] = "BLOCK"
            readiness["arithmetic_blocker"] = reason if reason.startswith("RESEARCH_") else type(exc).__name__
    return OperationResult(operation_id=operation.operation_id, status="BLOCK", exit_code=2,
                           errors=[FORMAL_BLOCKER], artifacts=artifacts,
                           metrics={"research_readiness": readiness})
