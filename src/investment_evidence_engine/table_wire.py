"""Explicit bounded tabular transport; never infer missing values as zero."""
from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any

MAX_ROWS = 10_000
MAX_COLUMNS = 512
MAX_CELLS = 1_000_000


def _shape(columns: list, rows: list) -> None:
    if (len(columns) > MAX_COLUMNS or len(rows) > MAX_ROWS
            or len(columns) * len(rows) > MAX_CELLS
            or any(not isinstance(c, str) or not c for c in columns)
            or len(set(columns)) != len(columns)
            or any(not isinstance(row, list) or len(row) != len(columns) for row in rows)):
        raise ValueError("invalid or oversized table")


def _encode_cell(value: Any) -> str | bool | int | float | None:
    import pandas as pd

    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else None
    # Pandas/numpy scalar, not an arbitrary object's serialization.
    import numpy as np

    if isinstance(value, np.generic):
        if isinstance(value, np.datetime64):
            return None if np.isnat(value) else pd.Timestamp(value).isoformat()
        converted = value.item()
        if type(converted) is type(value):
            raise ValueError("unsupported numpy scalar")
        return _encode_cell(converted)
    raise ValueError("unsupported table cell")


def pack_frame(frame: Any) -> dict | None:
    if frame is None:
        return None
    columns = list(frame.columns)
    nrows, ncols = frame.shape
    if nrows > MAX_ROWS or ncols > MAX_COLUMNS or nrows * ncols > MAX_CELLS:
        raise ValueError("table exceeds limit")
    if any(not isinstance(c, str) or not c for c in columns) or len(set(columns)) != len(columns):
        raise ValueError("invalid table columns")
    rows = [[_encode_cell(v) for v in row] for row in frame.itertuples(index=False, name=None)]
    _shape(columns, rows)
    return {"columns": columns, "rows": rows}


def unpack_frame(payload: dict | None) -> Any:
    if payload is None:
        return None
    import pandas as pd

    if not isinstance(payload, dict) or set(payload) != {"columns", "rows"}:
        raise ValueError("invalid table envelope")
    columns, rows = payload["columns"], payload["rows"]
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError("invalid table shape")
    _shape(columns, rows)
    if any(type(v) not in {str, int, float, bool, type(None)}
           or (type(v) is float and not math.isfinite(v)) for row in rows for v in row):
        raise ValueError("invalid table cell")
    return pd.DataFrame(rows, columns=columns, dtype=object)
