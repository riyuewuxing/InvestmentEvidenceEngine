from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from datetime import date
from numbers import Real
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from .contracts import ArtifactRef, ExecutionOperation, OperationResult
from .evidence_time_guard import (
    SHANGHAI,
    market_daily_label,
    parse_event_stamp,
    source_visible,
    validate_event_cutoff,
)
from .snapshot_integrity import strict_json_loads
from .transport_integrity import read_verified_artifact
from .workers import WorkerContext


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _artifact(path: Path, media_type: str = "application/json") -> ArtifactRef:
    return ArtifactRef(
        path=path.name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        media_type=media_type,
        size_bytes=path.stat().st_size,
    )


def _pit_record_inputs(operation: ExecutionOperation, context: WorkerContext) -> tuple[list[dict], dict]:
    """Validate the complete declared source set; never silently skip a dependency."""
    params = operation.parameters
    if "inline_records" in params and "depends_on_operation_ids" in params:
        raise ValueError("PIT_REPLAY_DEPENDENCY_INLINE_CONFLICT")
    if "inline_records" in params:
        inline = params["inline_records"]
        if not isinstance(inline, list) or not all(isinstance(row, dict) for row in inline):
            raise ValueError("PIT_REPLAY_INLINE_RECORDS_INVALID")
        return [dict(row) for row in inline], {"input_mode": "INLINE", "dependency_rows": {}}
    if "depends_on_operation_ids" not in params:
        return [], {"input_mode": "NONE", "dependency_rows": {}}
    deps = params["depends_on_operation_ids"]
    if (not isinstance(deps, list) or not deps or len(deps) > 64
            or not all(isinstance(dep, str) and dep and dep.strip() == dep for dep in deps)
            or len(set(deps)) != len(deps) or operation.operation_id in deps):
        raise ValueError("PIT_REPLAY_DEPENDENCY_SCOPE_INVALID")
    rows, counts, receipts = [], {}, {}
    for dep in deps:
        provenance = context.completed_operations.get(dep)
        payload = context.payloads.get(dep)
        if (not isinstance(provenance, dict) or provenance.get("status") not in {"PASS", "WARN"}
                or not isinstance(payload, dict)):
            raise ValueError("PIT_REPLAY_DEPENDENCY_NOT_USABLE")
        # A single explicit row collection, no hidden preference among tables,
        # no summary metrics substituted for records.
        present = [(key, payload[key]) for key in ("records", "bars", "rows", "data", "eligible_records")
                   if key in payload]
        if len(present) != 1:
            raise ValueError("PIT_REPLAY_DEPENDENCY_COLLECTION_AMBIGUOUS_OR_MISSING")
        key, records = present[0]
        if not isinstance(records, list) or not records or not all(isinstance(row, dict) for row in records):
            raise ValueError("PIT_REPLAY_DEPENDENCY_RECORDS_INVALID")
        refs = provenance.get("artifact_refs")
        if not isinstance(refs, list) or len(refs) != 1:
            raise ValueError("PIT_REPLAY_DEPENDENCY_ARTIFACT_REQUIRED")
        try:
            ref = ArtifactRef.model_validate(refs[0])
            if ref.path != dep + ".json" or ref.size_bytes is None:
                raise ValueError("PIT_REPLAY_DEPENDENCY_ARTIFACT_SCOPE")
            raw = read_verified_artifact(context.output_dir, ref.path, ref.sha256, ref.size_bytes)
            observed = strict_json_loads(raw)
            if (json.dumps(observed, sort_keys=True, allow_nan=False, ensure_ascii=False)
                    != json.dumps(payload, sort_keys=True, allow_nan=False, ensure_ascii=False)):
                raise ValueError("PIT_REPLAY_DEPENDENCY_CONTEXT_MISMATCH")
        except (ValueError, OSError, TypeError, OverflowError) as exc:
            reason = str(exc)
            raise ValueError(reason if reason.startswith("PIT_REPLAY_") else
                             "PIT_REPLAY_DEPENDENCY_ARTIFACT_UNVERIFIED") from exc
        counts[dep] = len(records)
        receipts[dep] = {"operation_kind": provenance.get("kind"), "operation_status": provenance["status"],
                         "artifact_path": ref.path, "artifact_sha256": ref.sha256,
                         "artifact_size_bytes": ref.size_bytes, "artifact_rehash": "MATCH",
                         "record_collection": key, "record_count": len(records),
                         "start_index": len(rows)}
        rows.extend(dict(row) for row in records)
    return rows, {"input_mode": "DEPENDENCIES", "dependency_rows": counts,
                  "dependency_artifacts": receipts}


def run_pit_replay(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    """Check stated observation chronology, never attest historical source vintage."""
    cutoff_raw = operation.parameters.get("as_of")
    cutoff, day_scope = validate_event_cutoff(cutoff_raw)
    if cutoff is None:
        raise ValueError("PIT_REPLAY requires as_of")
    # An operation may narrow, but never extend, the sealed request scope.
    if context.request_as_of is not None:
        ceiling, ceiling_day_only = validate_event_cutoff(context.request_as_of)
        if ceiling is None:
            raise ValueError("PIT_REPLAY_REQUEST_CUTOFF_REQUIRED")
        if ceiling_day_only:
            op_day = cutoff.date() if day_scope else cutoff.astimezone(SHANGHAI).date()
            outside = op_day > ceiling.date()
        elif day_scope:
            # A whole-day filter cannot prove an intraday ceiling.
            outside = True
        else:
            outside = cutoff > ceiling
        if outside:
            return OperationResult(operation_id=operation.operation_id, status="BLOCK", exit_code=2,
                                   errors=["PIT_REPLAY_REQUEST_SCOPE_EXCEEDED"])
    try:
        records, input_scope = _pit_record_inputs(operation, context)
    except ValueError as exc:
        return OperationResult(operation_id=operation.operation_id, status="BLOCK", exit_code=2,
                               errors=[str(exc)])
    available_field = operation.parameters.get("available_at_field", "available_at")
    published_field = operation.parameters.get("published_at_field", "published_at")
    retrieved_field = operation.parameters.get("retrieved_at_field", "retrieved_at")
    strict = operation.parameters.get("strict", True)
    fields = (available_field, published_field, retrieved_field)
    reserved = {"admitted_at", "durable_verified_at", "effective_at", "observed_at", "ingested_at"}
    canonical = ("available_at", "published_at", "retrieved_at")
    if (type(strict) is not bool or any(not isinstance(f, str) or not f or f.strip() != f for f in fields)
            or len(set(fields)) != 3 or any(f in reserved for f in fields)
            or any(f in canonical and f != expected for f, expected in zip(fields, canonical, strict=True))):
        raise ValueError("PIT_REPLAY_INVALID_FIELD_OR_STRICT_SCOPE")

    eligible = []
    eligible_indices = []
    future = []
    missing_availability = []
    invalid_chronology = []
    for index, record in enumerate(records):
        available, _ = parse_event_stamp(record.get(available_field))
        retrieved, _ = parse_event_stamp(record.get(retrieved_field))
        published_raw = record.get(published_field)
        published, _ = parse_event_stamp(published_raw)
        # Canonical clocks must not be hidden by an explicit alias. Additional
        # verification/admission clocks, when present, must also respect cutoff.
        clock_aliases = ((available_field, "available_at", available),
                         (retrieved_field, "retrieved_at", retrieved),
                         (published_field, "published_at", published))
        aliases = [parse_event_stamp(record.get(key))[0] for custom, key, _ in clock_aliases
                   if custom != key and key in record]
        extra = [parse_event_stamp(record.get(key))[0] for key in ("admitted_at", "durable_verified_at")
                 if key in record]
        # A producer may carry separate capture/ingest and effective clocks.
        # They are not interchangeable with publication or availability.
        observed = {key: parse_event_stamp(record.get(key))[0]
                    for key in ("observed_at", "ingested_at") if key in record}
        effective = parse_event_stamp(record.get("effective_at"))[0] if "effective_at" in record else None
        alias_conflict = any(
            parse_event_stamp(record.get(key))[0] != stamp
            or (record.get(key) is not None and parse_event_stamp(record.get(key))[0] is None)
            for custom, key, stamp in clock_aliases if custom != key and key in record
        )
        # Detect explicit future evidence even when the other fields are absent.
        stamps = (available, retrieved, published, *aliases, *extra, *observed.values(), effective)
        if day_scope:
            later = any(stamp is not None and
                (stamp.astimezone(SHANGHAI) if stamp.utcoffset() is not None else stamp).date()
                > cutoff.date() for stamp in stamps)
        else:
            later = any(stamp is not None and stamp.utcoffset() is not None
                        and stamp > cutoff for stamp in stamps)
        if later:
            future.append(index)
            continue
        if available is None or retrieved is None:
            missing_availability.append(index)
            continue
        if (day_scope or alias_conflict or (published_raw is not None and published is None)
                or not source_visible(available_at=available, retrieved_at=retrieved,
                                      published_at=published, cutoff=cutoff)
                or any(not source_visible(available_at=available, retrieved_at=retrieved,
                                          published_at=published, cutoff=cutoff, admitted_at=stamp)
                       or stamp is None for stamp in extra)
                or any(stamp is None or stamp.utcoffset() is None or not retrieved <= stamp <= cutoff
                       for stamp in observed.values())
                or ("effective_at" in record and (effective is None or effective.utcoffset() is None
                    or effective > available))
                or ("observed_at" in observed and "ingested_at" in observed
                    and observed["observed_at"] > observed["ingested_at"])
                or (observed and any(stamp < max(observed.values()) for stamp in extra))):
            invalid_chronology.append(index)
            continue
        eligible.append(record)
        eligible_indices.append(index)

    blockers = []
    if day_scope:
        blockers.append("EXACT_AWARE_CUTOFF_REQUIRED")
    if future:
        blockers.append(f"FUTURE_RECORDS_REJECTED:{len(future)}")
    if missing_availability:
        blockers.append(f"MISSING_AVAILABILITY_OR_RETRIEVAL:{len(missing_availability)}")
    if invalid_chronology:
        blockers.append(f"INVALID_OR_UNVERIFIED_CHRONOLOGY:{len(invalid_chronology)}")
    if not records:
        blockers.append("NO_REPLAY_RECORDS")
    elif not eligible:
        blockers.append("NO_CHRONOLOGY_ELIGIBLE_RECORDS")
    # Even complete caller-supplied timestamps do not prove the bytes existed then.
    # The non-strict mode may expose a partial chronology diagnostic, never PIT-safe.
    status = "BLOCK" if blockers and (strict or not eligible or future) else "WARN"
    warnings = ["CALLER_STATED_CHRONOLOGY_NOT_HISTORICAL_VINTAGE_OR_ADMISSION"]
    if blockers and status == "WARN":
        warnings.extend(blockers)
    payload = {
        "as_of": cutoff_raw,
        "input_count": len(records),
        "input_scope": input_scope,
        "eligible_count": len(eligible),
        "future_rejected_count": len(future),
        "missing_availability_count": len(missing_availability),
        "invalid_chronology_count": len(invalid_chronology),
        "eligible_records": eligible,
        "eligible_input_indices": eligible_indices,
        "strict": strict,
        "chronology_complete": not blockers,
        "pit_safe": False,
        "historical_vintage_verified": False,
        "decision_authority": False,
        "warnings": warnings,
    }
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    context.payloads[operation.operation_id] = payload
    return OperationResult(
        operation_id=operation.operation_id,
        status=status,
        exit_code=2 if status == "BLOCK" else 0,
        artifacts=[_artifact(path)],
        metrics={key: payload[key] for key in (
            "input_count", "eligible_count", "future_rejected_count", "missing_availability_count",
            "invalid_chronology_count", "chronology_complete", "pit_safe"
        )},
        warnings=warnings,
        errors=blockers if status == "BLOCK" else [],
    )


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _compute_block(operation: ExecutionOperation, reason: str) -> OperationResult:
    return OperationResult(operation_id=operation.operation_id, status="BLOCK",
                           exit_code=2, errors=[reason])


def _compute_records(operation: ExecutionOperation, context: WorkerContext) -> tuple[list[dict], dict]:
    """Use one explicit record collection from one rehashed dependency, or inline rows."""
    params = operation.parameters
    if "depends_on_operation_ids" not in params:
        inline = params.get("inline_records")
        if not isinstance(inline, list) or not all(isinstance(row, dict) for row in inline):
            return [], {"input_mode": "NONE_OR_INVALID"}
        return [dict(row) for row in inline], {"input_mode": "INLINE", "record_count": len(inline)}
    if "inline_records" in params:
        raise ValueError("COMPUTE_DEPENDENCY_INLINE_CONFLICT")
    deps = params["depends_on_operation_ids"]
    if (not isinstance(deps, list) or len(deps) != 1
            or not isinstance(deps[0], str) or not deps[0]
            or deps[0] != deps[0].strip() or deps[0] == operation.operation_id):
        raise ValueError("COMPUTE_EXACTLY_ONE_DEPENDENCY_REQUIRED")
    dep = deps[0]
    provenance = context.completed_operations.get(dep)
    payload = context.payloads.get(dep)
    if (not isinstance(provenance, dict) or provenance.get("status") not in {"PASS", "WARN"}
            or not isinstance(payload, dict)):
        raise ValueError("COMPUTE_DEPENDENCY_NOT_USABLE")
    # Never pick the first of several tables, treat summary metrics as rows,
    # or fall back from a malformed declared table to another one.
    keys = [key for key in ("records", "bars", "rows", "data", "eligible_records") if key in payload]
    if len(keys) != 1:
        raise ValueError("COMPUTE_DEPENDENCY_COLLECTION_AMBIGUOUS_OR_MISSING")
    key = keys[0]
    records = payload[key]
    if not isinstance(records, list) or not records or not all(isinstance(row, dict) for row in records):
        raise ValueError("COMPUTE_DEPENDENCY_RECORDS_INVALID")
    refs = provenance.get("artifact_refs")
    if not isinstance(refs, list) or len(refs) != 1:
        raise ValueError("COMPUTE_DEPENDENCY_ARTIFACT_REQUIRED")
    try:
        ref = ArtifactRef.model_validate(refs[0])
        if ref.path != dep + ".json" or ref.size_bytes is None:
            raise ValueError("COMPUTE_DEPENDENCY_ARTIFACT_SCOPE")
        raw = read_verified_artifact(context.output_dir, ref.path, ref.sha256, ref.size_bytes)
        observed = strict_json_loads(raw)
        # Canonical JSON preserves type distinctions such as boolean vs number.
        if (json.dumps(observed, sort_keys=True, allow_nan=False, ensure_ascii=False)
                != json.dumps(payload, sort_keys=True, allow_nan=False, ensure_ascii=False)):
            raise ValueError("COMPUTE_DEPENDENCY_CONTEXT_MISMATCH")
    except (ValueError, OSError, TypeError, OverflowError) as exc:
        reason = str(exc)
        raise ValueError(reason if reason.startswith("COMPUTE_") else
                         "COMPUTE_DEPENDENCY_ARTIFACT_UNVERIFIED") from exc
    records = [dict(row) for row in records]
    date_projection = "UNCHANGED"
    if provenance.get("kind") == "MARKET_DATA":
        if key != "bars":
            raise ValueError("COMPUTE_MARKET_COLLECTION_MISMATCH")
        symbol = payload.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("COMPUTE_MARKET_IDENTITY_MISSING")
        if params.get("subject_ids", [symbol]) != [symbol]:
            raise ValueError("COMPUTE_MARKET_IDENTITY_MISMATCH")
        for row in records:
            for identity in ("subject_id", "asset", "asset_id", "symbol", "code"):
                if identity in row and row[identity] != symbol:
                    raise ValueError("COMPUTE_MARKET_IDENTITY_MISMATCH")
        # The bound production daily-bar JSON uses a midnight date placeholder.
        # It is not an acquisition/publication timestamp. Do not relax inline or other sources.
        records = [dict(row, symbol=symbol, date=market_daily_label(row.get("date"))) for row in records]
        date_projection = "MARKET_DAILY_LABEL_ONLY"
    scope = {"input_mode": "DEPENDENCY", "operation_id": dep,
             "operation_kind": provenance.get("kind"), "operation_status": provenance["status"],
             "artifact_path": ref.path, "artifact_sha256": ref.sha256,
             "artifact_size_bytes": ref.size_bytes, "artifact_rehash": "MATCH",
             "record_collection": key, "record_count": len(records),
             "date_projection": date_projection}
    return records, scope


def _record_time_labels(records: list[dict], parameters: dict, *, required: bool,
                        request_as_of: str | None = None) -> list | None:
    """Validate every declared observation label against both ceilings.

    Labels are not evidence of publication, acquisition, or market-session completeness.
    An explicit time_field cannot hide another recognized future observation label.
    """
    explicit = parameters.get("time_field")
    if explicit is not None and (not isinstance(explicit, str) or not explicit.strip()):
        raise ValueError("COMPUTE_TIME_FIELD_INVALID")
    recognized = [k for k in ("date", "session", "timestamp")
                  if any(k in row for row in records)]
    field = explicit or next(iter(recognized), None)
    ceilings = [validate_event_cutoff(scope) for scope in
                (request_as_of, parameters.get("as_of")) if scope is not None]
    if field is None:
        if required:
            raise ValueError("COMPUTE_TIME_FIELD_REQUIRED")
        return None
    selected = None
    for key in dict.fromkeys([field, *recognized]):
        stamps = [parse_event_stamp(row.get(key)) for row in records]
        if any(stamp is None or (not day and stamp.utcoffset() is None) for stamp, day in stamps):
            raise ValueError("COMPUTE_TIME_LABEL_INVALID")
        if len({day for _, day in stamps}) != 1:
            raise ValueError("COMPUTE_MIXED_TIME_PRECISION")
        for cutoff, day_scope in ceilings:
            for stamp, day in stamps:
                if day_scope:
                    local_day = stamp.date() if day else stamp.astimezone(SHANGHAI).date()
                    outside = local_day > cutoff.date()
                elif day:
                    outside = stamp.date() >= cutoff.astimezone(SHANGHAI).date()
                else:
                    outside = stamp > cutoff
                if outside:
                    raise ValueError("COMPUTE_RECORD_AFTER_OR_UNPROVEN_AT_CUTOFF")
        if key == field:
            selected = [stamp for stamp, _ in stamps]
    return selected


def _chronological_rows(records: list[dict], parameters: dict, *, required: bool,
                        request_as_of: str | None = None) -> bool:
    """Date/instant label order only, not actual availability or market calendar proof."""
    # Time-series operations cannot blend two distinct security identities.
    for key in ("subject_id", "asset", "asset_id", "symbol", "code"):
        if any(key in row for row in records):
            values = [row.get(key) for row in records]
            if (not all(isinstance(v, str) and v.strip() for v in values)
                    or len(set(values)) != 1):
                raise ValueError("COMPUTE_MULTIPLE_OR_MISSING_SUBJECTS")
    dates = _record_time_labels(records, parameters, required=required,
                                request_as_of=request_as_of)
    if dates is None:
        return False
    if dates != sorted(set(dates)):
        raise ValueError("COMPUTE_TIME_ORDER_OR_DUPLICATE")
    return True


def run_factor_compute(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    try:
        records, input_scope = _compute_records(operation, context)
    except ValueError as exc:
        return _compute_block(operation, str(exc))
    if not records:
        return _compute_block(operation, "NO_FACTOR_INPUT_RECORDS")
    spec = operation.parameters.get("factor_spec")
    if not isinstance(spec, dict):
        return _compute_block(operation, "FACTOR_SPEC_REQUIRED")
    field = spec.get("field")
    transform = str(spec.get("transform") or "IDENTITY").upper()
    if not isinstance(field, str) or not field.strip():
        return _compute_block(operation, "FACTOR_FIELD_REQUIRED")
    frame = pd.DataFrame(records)
    if field not in frame.columns:
        return _compute_block(operation, f"FACTOR_FIELD_MISSING:{field}")
    values_raw = [row.get(field) for row in records]
    if any(v is not None and not _is_finite_number(v) for v in values_raw):
        return _compute_block(operation, "FACTOR_NONFINITE_OR_NONNUMERIC_INPUT")
    values = pd.Series(values_raw, dtype="float64", index=frame.index)
    temporal = transform in {"PCT_CHANGE", "ROLLING_MEAN", "ROLLING_RETURN"}
    chronology = False
    label_scope = "UNLABELED_DIAGNOSTIC"
    try:
        if temporal:
            chronology = _chronological_rows(records, operation.parameters, required=True,
                                             request_as_of=context.request_as_of)
            label_scope = "ORDERED_TIME_LABELS"
        else:
            labels = _record_time_labels(records, operation.parameters, required=False,
                                         request_as_of=context.request_as_of)
            if labels is not None:
                label_scope = "DECLARED_OBSERVATION_LABELS"
                if transform in {"RANK_PCT", "Z_SCORE"}:
                    if len(set(labels)) != 1:
                        raise ValueError("FACTOR_MULTI_TIME_BATCH_NORMALIZATION_FORBIDDEN")
                    label_scope = "SINGLE_DECLARED_SNAPSHOT_LABEL"
    except ValueError as exc:
        return _compute_block(operation, str(exc))
    if temporal:
        key = "periods" if transform == "PCT_CHANGE" else "window"
        window = spec.get(key, 1 if transform == "PCT_CHANGE" else 20)
        if type(window) is not int or not (2 if transform == "ROLLING_MEAN" else 1) <= window <= 10000:
            return _compute_block(operation, "FACTOR_WINDOW_INVALID")
    if transform == "IDENTITY":
        factor = values
    elif transform == "RANK_PCT":
        factor = values.rank(method="average", pct=True)
    elif transform == "Z_SCORE":
        std = float(values.std(ddof=0))
        mean = float(values.mean())
        if not math.isfinite(std) or not math.isfinite(mean):
            return _compute_block(operation, "FACTOR_NORMALIZATION_NONFINITE")
        factor = (values - mean) / std if std > 0 else values * 0.0
    elif transform == "PCT_CHANGE":
        factor = values.pct_change(periods=window, fill_method=None)
    elif transform == "ROLLING_MEAN":
        factor = values.rolling(window, min_periods=window).mean()
    elif transform == "ROLLING_RETURN":
        factor = values / values.shift(window) - 1.0
    else:
        return _compute_block(operation, f"UNSUPPORTED_FACTOR_TRANSFORM:{transform}")
    # Undefined ratios, missing observations and warmup are missing, never zeros.
    factor = factor.where(np.isfinite(factor))
    if not factor.notna().any():
        return _compute_block(operation, "FACTOR_NO_FINITE_OUTPUT")
    output_field = spec.get("output_field", "factor_value")
    if not isinstance(output_field, str) or not output_field.strip() or output_field in frame.columns:
        return _compute_block(operation, "FACTOR_OUTPUT_FIELD_COLLISION_OR_INVALID")
    frame[output_field] = factor
    output = json.loads(frame.to_json(orient="records", date_format="iso", force_ascii=False))
    finite = factor.dropna()
    statistics = {"count": int(finite.count()), "mean": float(finite.mean()),
                  "std": float(finite.std(ddof=0)), "min": float(finite.min()), "max": float(finite.max())}
    if not all(math.isfinite(v) for v in statistics.values()):
        return _compute_block(operation, "FACTOR_STATISTICS_NONFINITE")
    payload = {
        "compute_input_scope": input_scope,
        "factor_id": str(spec.get("factor_id") or operation.operation_id),
        "transform": transform, "source_field": field, "output_field": output_field,
        "records": output, "statistics": statistics,
        "missing_input_count": int(values.isna().sum()),
        "undefined_output_count": int(factor.isna().sum()),
        "missing_values_filled": False, "time_label_order_verified": chronology,
        "observation_label_scope": label_scope,
        "batch_normalization_basis": ("WHOLE_INPUT_NOT_HISTORICAL_SIGNAL"
                                      if transform in {"RANK_PCT", "Z_SCORE"} else None),
        "lookback_basis": "ORDERED_INPUT_ROWS_NOT_VERIFIED_SESSIONS" if temporal else None,
        "historical_vintage_verified": False, "pit_safe": False, "decision_authority": False,
    }
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    context.payloads[operation.operation_id] = payload
    return OperationResult(operation_id=operation.operation_id, status="PASS", exit_code=0,
                           artifacts=[_artifact(path)], metrics=statistics)


def _max_drawdown(equity: pd.Series) -> float | None:
    if equity.empty:
        return None
    # Initial wealth is one; a first-row fee or loss must count as drawdown.
    peaks = equity.cummax().clip(lower=1.0)
    return float((equity / peaks - 1.0).min())


def run_backtest(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    """Single-series arithmetic diagnostic; not a historical executable strategy."""
    parameters = operation.parameters
    try:
        records, input_scope = _compute_records(operation, context)
        if not records:
            return _compute_block(operation, "NO_BACKTEST_INPUT_RECORDS")
        chronology = _chronological_rows(records, parameters,
                                         required="depends_on_operation_ids" in parameters,
                                         request_as_of=context.request_as_of)
    except ValueError as exc:
        return _compute_block(operation, str(exc))
    return_field = parameters.get("return_field", "return")
    weight_field = parameters.get("weight_field", "weight")
    if (not isinstance(return_field, str) or not return_field or not isinstance(weight_field, str)
            or not weight_field or return_field == weight_field):
        return _compute_block(operation, "BACKTEST_FIELDS_INVALID")
    returns_raw = [row.get(return_field) for row in records]
    weights_raw = [row.get(weight_field) for row in records]
    if not all(_is_finite_number(v) and v >= -1 for v in returns_raw):
        return _compute_block(operation, "BACKTEST_RETURN_MISSING_OR_INVALID")
    if not all(_is_finite_number(v) and 0 <= v <= 1 for v in weights_raw):
        return _compute_block(operation, "BACKTEST_WEIGHT_MISSING_OR_INVALID")
    cost_bps = parameters.get("cost_bps")
    if not _is_finite_number(cost_bps) or not 0 <= cost_bps < 10000:
        return _compute_block(operation, "BACKTEST_EXPLICIT_COST_ASSUMPTION_REQUIRED")
    periods_per_year = parameters.get("periods_per_year")
    if periods_per_year is not None and (type(periods_per_year) is not int or not 1 <= periods_per_year <= 100000):
        return _compute_block(operation, "BACKTEST_ANNUALIZATION_ASSUMPTION_INVALID")
    returns = pd.Series(returns_raw, dtype="float64")
    weights = pd.Series(weights_raw, dtype="float64")
    lag_weights = weights.shift(1, fill_value=0.0)
    gross = lag_weights * returns
    turnover = (weights - lag_weights).abs()
    net = gross - turnover * cost_bps / 10000.0
    if not np.isfinite(net).all() or (net <= -1).any():
        return _compute_block(operation, "BACKTEST_NONPOSITIVE_PERIOD_WEALTH")
    equity = (1.0 + net).cumprod()
    if not np.isfinite(equity).all() or (equity <= 0).any():
        return _compute_block(operation, "BACKTEST_NONFINITE_OR_NONPOSITIVE_WEALTH")
    n = len(net)
    total_return = float(equity.iloc[-1] - 1.0)
    annualized_return, annualized_vol, sharpe = None, None, None
    if periods_per_year is not None:
        try:
            annualized_return = math.expm1(math.log(float(equity.iloc[-1])) * periods_per_year / n)
            sd = float(net.std(ddof=1)) if n >= 2 else None
            annualized_vol = sd * math.sqrt(periods_per_year) if sd is not None else None
            sharpe = (float(net.mean()) / sd * math.sqrt(periods_per_year)
                      if sd is not None and sd > 0 else None)
        except (ArithmeticError, ValueError):
            return _compute_block(operation, "BACKTEST_ANNUALIZATION_NONFINITE")
    metrics = {
        "observations": n, "total_return": total_return,
        "annualized_return": annualized_return, "annualized_volatility": annualized_vol,
        "sharpe_zero_rf": sharpe, "max_drawdown": _max_drawdown(equity),
        "total_turnover": float(turnover.sum()), "cost_bps": float(cost_bps), "net_of_costs": True,
    }
    if any(v is not None and type(v) is not bool and not math.isfinite(v) for v in metrics.values()):
        return _compute_block(operation, "BACKTEST_METRICS_NONFINITE")
    payload = {
        "metrics": metrics,
        "compute_input_scope": input_scope,
        "assumptions": {
            "signal_lag_periods": 1, "periods_per_year": periods_per_year,
            "cost_applied_to_turnover": True, "cost_basis": "LINEAR_TARGET_WEIGHT_CHANGE_ASSUMPTION",
            "initial_weight": 0.0, "terminal_liquidation_assumed": False,
            "annualization_cadence_verified": False, "actual_costs_verified": False,
            "missing_returns_or_weights_imputed": False,
        },
        "time_label_order_verified": chronology,
        "research_only": True, "pit_safe": False, "historical_vintage_verified": False,
        "actual_trade_feasibility_verified": False, "decision_authority": False,
    }
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    context.payloads[operation.operation_id] = payload
    return OperationResult(operation_id=operation.operation_id, status="PASS", exit_code=0,
                           artifacts=[_artifact(path)], metrics=metrics)


_OPERATOR: dict[str, Callable[[pd.Series, float], pd.Series]] = {
    "GT": lambda series, value: series > value,
    "GE": lambda series, value: series >= value,
    "LT": lambda series, value: series < value,
    "LE": lambda series, value: series <= value,
}


_LIVE_SCAN_NUMERIC_FIELDS = {
    "latest_price",
    "pct_change",
    "volume",
    "amount",
    "amplitude",
    "turnover_rate",
    "pe_dynamic",
    "pb",
    "total_market_cap",
    "float_market_cap",
    "change_60d",
    "ytd_change",
}
_SCAN_RULE_KEYS = {"field", "operator", "threshold", "weight"}


def _scan_block(error: str) -> OperationResult:
    return OperationResult(
        operation_id="",
        status="BLOCK",
        exit_code=2,
        errors=[error],
    )


def _scan_as_of(value: object) -> str | None:
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value)
        return parsed.isoformat() if value == parsed.isoformat() else None
    except (TypeError, ValueError):
        return None


def _scan_scope(parameters: dict[str, object], key: str, default: str) -> str:
    value = parameters.get(key)
    return default if value is None or not str(value).strip() else str(value).strip().upper()


def _scan_input(
    operation: ExecutionOperation,
    context: WorkerContext,
) -> tuple[list[dict[str, object]], str, dict[str, object] | None, str | None] | OperationResult:
    parameters = operation.parameters
    has_dependency = "depends_on_operation_ids" in parameters
    has_inline = "inline_records" in parameters
    if has_dependency:
        if has_inline:
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_INLINE_CONFLICT")
        dependencies = parameters.get("depends_on_operation_ids")
        if not isinstance(dependencies, list) or len(dependencies) != 1:
            return _scan_block("OPPORTUNITY_SCAN_REQUIRES_SINGLE_DEPENDENCY")
        dependency_id = dependencies[0]
        if not isinstance(dependency_id, str):
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_ID_INVALID")
        provenance = context.completed_operations.get(dependency_id)
        if provenance is None:
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_NOT_COMPLETED")
        if provenance.get("kind") != "MARKET_UNIVERSE":
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_KIND_INVALID")
        if provenance.get("status") not in {"PASS", "WARN"}:
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_STATUS_INVALID")
        operation_as_of = _scan_as_of(parameters.get("as_of"))
        request_as_of = _scan_as_of(context.request_as_of)
        if (
            operation_as_of is None
            or request_as_of is None
            or _scan_as_of(provenance.get("as_of")) != operation_as_of
            or operation_as_of != request_as_of
        ):
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_AS_OF_INVALID")
        payload = context.payloads.get(dependency_id)
        if not isinstance(payload, dict):
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_PAYLOAD_INVALID")
        if (
            payload.get("source") != "public_market_data"
            or payload.get("public_data_only") is not True
            or payload.get("decision_authority") is not False
        ):
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_PAYLOAD_INVALID")
        if (
            _scan_scope(parameters, "market", "CN_A") != provenance.get("market")
            or _scan_scope(parameters, "asset_type", "STOCK") != provenance.get("asset_type")
            or _scan_scope(parameters, "market", "CN_A") != payload.get("market")
            or _scan_scope(parameters, "asset_type", "STOCK") != payload.get("asset_type")
        ):
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_SCOPE_INVALID")
        payload_as_of = _scan_as_of(payload.get("as_of"))
        if (
            operation_as_of is None
            or request_as_of is None
            or payload_as_of is None
            or operation_as_of != request_as_of
            or operation_as_of != payload_as_of
        ):
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_AS_OF_INVALID")
        records = payload.get("records")
        if not isinstance(records, list) or not records or not all(isinstance(item, dict) for item in records):
            return _scan_block("OPPORTUNITY_SCAN_DEPENDENCY_RECORDS_MISSING")
        listing_crosscheck = payload.get("listing_crosscheck")
        listing_status = listing_crosscheck.get("status") if isinstance(listing_crosscheck, dict) else None
        dependency_evidence = {
            "operation_id": dependency_id,
            "kind": provenance.get("kind"),
            "status": provenance.get("status"),
            "as_of": operation_as_of,
            "market": payload.get("market"),
            "asset_type": payload.get("asset_type"),
            "source": payload.get("source"),
            "provider": payload.get("provider"),
            "primary_provider": payload.get("primary_provider"),
            "quote_trade_date_status": payload.get("quote_trade_date_status"),
            "listing_crosscheck": {"status": listing_status},
            "quality_flags": [
                item for item in payload.get("quality_flags", [])[:16] if isinstance(item, str)
            ],
            "warnings": [item for item in payload.get("warnings", [])[:16] if isinstance(item, str)],
        }
        return [dict(item) for item in records], "LIVE_MARKET_UNIVERSE", dependency_evidence, str(
            provenance.get("status")
        )
    if not has_inline:
        return _scan_block("OPPORTUNITY_SCAN_REQUIRES_RECORDS")
    records = parameters.get("inline_records")
    if not isinstance(records, list) or not records or not all(isinstance(item, dict) for item in records):
        return _scan_block("OPPORTUNITY_SCAN_INLINE_RECORDS_INVALID")
    return [dict(item) for item in records], "INLINE_SYNTHETIC", None, None


def _is_finite_number(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(float(value))


def _is_missing_value(value: object) -> bool:
    if value is None:
        return True
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return isinstance(missing, (bool, np.bool_)) and bool(missing)


def _validate_scan_semantics(parameters: dict[str, object]) -> str | None:
    if (
        "ranking_semantics" in parameters
        and parameters["ranking_semantics"] != "RESEARCH_PRIORITY_NOT_RETURN_FORECAST"
    ):
        return "OPPORTUNITY_SCAN_SEMANTICS_INVALID"
    if (
        "rule_origin" in parameters
        and parameters["rule_origin"] not in {"USER_PROVIDED_RESEARCH_FILTER", "SYSTEM_RESEARCH_FILTER"}
    ):
        return "OPPORTUNITY_SCAN_SEMANTICS_INVALID"
    return None


def _validate_scan_rules(
    parameters: dict[str, object],
    frame: pd.DataFrame,
    input_mode: str,
) -> tuple[list[dict[str, object]], int] | str:
    rules = parameters.get("rules")
    if not isinstance(rules, list) or not 1 <= len(rules) <= 32:
        return "OPPORTUNITY_SCAN_RULE_COUNT_INVALID"
    applied_rules: list[dict[str, object]] = []
    for index, raw_rule in enumerate(rules):
        if not isinstance(raw_rule, dict):
            return f"OPPORTUNITY_SCAN_RULE_NOT_OBJECT:{index}"
        extra = sorted(set(raw_rule) - _SCAN_RULE_KEYS)
        if extra:
            return f"OPPORTUNITY_SCAN_RULE_KEYS_INVALID:{index}"
        field = raw_rule.get("field")
        if not isinstance(field, str) or not field.strip():
            return f"OPPORTUNITY_SCAN_RULE_FIELD_INVALID:{index}"
        field = field.strip()
        if input_mode == "LIVE_MARKET_UNIVERSE" and field not in _LIVE_SCAN_NUMERIC_FIELDS:
            return f"OPPORTUNITY_SCAN_LIVE_FIELD_INVALID:{field}"
        if field not in frame.columns:
            return f"OPPORTUNITY_SCAN_RULE_FIELD_MISSING:{field}"
        values = frame[field].tolist()
        if input_mode == "LIVE_MARKET_UNIVERSE":
            present_values = [value for value in values if not _is_missing_value(value)]
            if not present_values:
                return f"OPPORTUNITY_SCAN_RULE_FIELD_NO_VALID_NUMERIC:{field}"
            if not all(_is_finite_number(value) for value in present_values):
                return f"OPPORTUNITY_SCAN_RULE_FIELD_NOT_NUMERIC:{field}"
        elif not all(_is_finite_number(value) for value in values):
            return f"OPPORTUNITY_SCAN_RULE_FIELD_NOT_NUMERIC:{field}"
        operator = raw_rule.get("operator")
        if not isinstance(operator, str) or operator not in _OPERATOR:
            return f"OPPORTUNITY_SCAN_RULE_OPERATOR_INVALID:{index}"
        if "threshold" not in raw_rule or not _is_finite_number(raw_rule["threshold"]):
            return f"OPPORTUNITY_SCAN_RULE_THRESHOLD_INVALID:{index}"
        threshold = float(raw_rule["threshold"])
        if "weight" not in raw_rule:
            weight = 1.0
        elif not _is_finite_number(raw_rule["weight"]) or float(raw_rule["weight"]) < 0:
            return f"OPPORTUNITY_SCAN_RULE_WEIGHT_INVALID:{index}"
        else:
            weight = float(raw_rule["weight"])
        applied_rules.append(
            {"field": field, "operator": operator, "threshold": threshold, "weight": weight}
        )
    top_n = parameters.get("top_n", 50)
    if not isinstance(top_n, int) or isinstance(top_n, bool) or not 1 <= top_n <= 1000:
        return "OPPORTUNITY_SCAN_TOP_N_INVALID"
    return applied_rules, top_n


def run_opportunity_scan(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    semantic_error = _validate_scan_semantics(operation.parameters)
    if semantic_error is not None:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=[semantic_error],
        )
    scan_input = _scan_input(operation, context)
    if isinstance(scan_input, OperationResult):
        return scan_input.model_copy(update={"operation_id": operation.operation_id})
    records, input_mode, dependency_evidence, dependency_status = scan_input
    frame = pd.DataFrame(records)
    validated = _validate_scan_rules(operation.parameters, frame, input_mode)
    if isinstance(validated, str):
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=[validated],
        )
    applied_rules, top_n = validated
    score = pd.Series(0.0, index=frame.index)
    matched_count = pd.Series(0, index=frame.index)
    for rule in applied_rules:
        field = str(rule["field"])
        operator = str(rule["operator"])
        threshold = float(rule["threshold"])
        weight = float(rule["weight"])
        matches = _OPERATOR[operator](_numeric(frame[field]), threshold).fillna(False)
        score = score + matches.astype(float) * weight
        matched_count = matched_count + matches.astype(int)
    frame["research_priority_score"] = score
    frame["matched_rule_count"] = matched_count
    sort_fields = ["research_priority_score", "matched_rule_count"]
    frame = frame.sort_values(sort_fields, ascending=[False, False], kind="stable")
    output = json.loads(frame.head(top_n).to_json(orient="records", date_format="iso", force_ascii=False))
    payload = {
        "candidates": output,
        "rules": applied_rules,
        "candidate_count": len(output),
        "ranking_semantics": "RESEARCH_PRIORITY_NOT_RETURN_FORECAST",
        "input_mode": input_mode,
        "rule_origin": operation.parameters.get("rule_origin", "UNSPECIFIED_RESEARCH_FILTER"),
        "screened_count": len(frame),
        "research_only": True,
        "pit_safe": False,
        "decision_authority": False,
    }
    if dependency_evidence is not None:
        payload["dependency_evidence"] = dependency_evidence
    warnings = (
        ["OPPORTUNITY_SCAN_DEPENDENCY_WARN"]
        if dependency_status == "WARN"
        else []
    )
    path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(path, payload)
    context.payloads[operation.operation_id] = payload
    return OperationResult(
        operation_id=operation.operation_id,
        status="WARN" if warnings else "PASS",
        exit_code=0,
        artifacts=[_artifact(path)],
        warnings=warnings,
        metrics={
            "candidate_count": len(output),
            "rule_count": len(applied_rules),
            "input_mode": input_mode,
        },
    )


def run_test_suite(operation: ExecutionOperation, context: WorkerContext) -> OperationResult:
    suites = operation.parameters.get("suites") or ["pytest"]
    if not isinstance(suites, list):
        raise ValueError("TEST_SUITE suites must be a list")
    allowlist = {
        "pytest": [sys.executable, "-m", "pytest", "-q"],
        "compile": [sys.executable, "-m", "compileall", "-q", "src"],
        "ruff": [sys.executable, "-m", "ruff", "check", "."],
    }
    unknown = [str(item) for item in suites if str(item) not in allowlist]
    if unknown:
        return OperationResult(
            operation_id=operation.operation_id,
            status="BLOCK",
            exit_code=2,
            errors=["UNSAFE_OR_UNKNOWN_TEST_SUITE:" + ",".join(unknown)],
        )
    logs: list[str] = []
    failures: list[str] = []
    for suite in [str(item) for item in suites]:
        completed = subprocess.run(
            allowlist[suite],
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        logs.append(f"## {suite}\nexit={completed.returncode}\n{completed.stdout}\n{completed.stderr}")
        if completed.returncode != 0:
            failures.append(f"{suite}:exit={completed.returncode}")
    path = context.output_dir / f"{operation.operation_id}.log"
    path.write_text("\n\n".join(logs), encoding="utf-8")
    payload = {
        "suites": [str(item) for item in suites],
        "failures": failures,
        "decision_authority": False,
    }
    json_path = context.output_dir / f"{operation.operation_id}.json"
    _write_json(json_path, payload)
    return OperationResult(
        operation_id=operation.operation_id,
        status="BLOCK" if failures else "PASS",
        exit_code=2 if failures else 0,
        artifacts=[_artifact(json_path), _artifact(path, "text/plain")],
        metrics={"suite_count": len(suites), "failure_count": len(failures)},
        errors=failures,
    )
