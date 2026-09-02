from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import pandas as pd


def _fingerprint(payload: object) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class SchemaCheck:
    status: str
    fingerprint: str
    columns: tuple[str, ...]
    dtypes: dict[str, str]
    missing_required: tuple[str, ...]
    unexpected_columns: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "fingerprint": self.fingerprint,
            "columns": list(self.columns),
            "dtypes": self.dtypes,
            "missing_required": list(self.missing_required),
            "unexpected_columns": list(self.unexpected_columns),
        }


def inspect_frame_schema(
    frame: pd.DataFrame,
    *,
    required_columns: tuple[str, ...] = (),
    allowed_columns: tuple[str, ...] | None = None,
) -> SchemaCheck:
    columns = tuple(str(column) for column in frame.columns)
    dtypes = {str(column): str(dtype) for column, dtype in frame.dtypes.items()}
    missing = tuple(column for column in required_columns if column not in columns)
    if allowed_columns is None:
        unexpected: tuple[str, ...] = ()
    else:
        allowed = set(allowed_columns)
        unexpected = tuple(column for column in columns if column not in allowed)
    status = "BLOCK" if missing else ("WARN" if unexpected else "PASS")
    payload = {"columns": columns, "dtypes": dtypes}
    return SchemaCheck(
        status=status,
        fingerprint=_fingerprint(payload),
        columns=columns,
        dtypes=dtypes,
        missing_required=missing,
        unexpected_columns=unexpected,
    )


OHLCV_REQUIRED = ("date", "open", "high", "low", "close", "volume")
OHLCV_ALLOWED = (*OHLCV_REQUIRED, "amount", "turnover")


def inspect_normalized_ohlcv(frame: pd.DataFrame) -> SchemaCheck:
    return inspect_frame_schema(
        frame,
        required_columns=OHLCV_REQUIRED,
        allowed_columns=OHLCV_ALLOWED,
    )


def compare_schema_fingerprint(
    observed: SchemaCheck,
    expected_fingerprint: str | None,
) -> dict[str, object]:
    if not expected_fingerprint:
        return {
            "status": observed.status,
            "baseline_present": False,
            "observed_fingerprint": observed.fingerprint,
            "drift": None,
        }
    drift = observed.fingerprint != expected_fingerprint
    status = "BLOCK" if observed.status == "BLOCK" else ("WARN" if drift else observed.status)
    return {
        "status": status,
        "baseline_present": True,
        "observed_fingerprint": observed.fingerprint,
        "expected_fingerprint": expected_fingerprint,
        "drift": drift,
    }
