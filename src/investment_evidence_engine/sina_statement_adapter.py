"""Single-call, inspected adapter for known AKShare Sina statement signatures."""
from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from typing import Any

STATEMENTS = {"资产负债表", "利润表", "现金流量表"}


def sina_statement_kwargs(fn: Callable, stock: str, statement: str) -> dict[str, str]:
    if not re.fullmatch(r"(sh|sz)[0-9]{6}", stock) or statement not in STATEMENTS:
        raise ValueError("invalid Sina statement identity")
    params = inspect.signature(fn).parameters
    names = set(params)
    if {"stock", "indicator"} <= names:
        kwargs = {"stock": stock, "indicator": statement}
    elif {"symbol", "indicator"} <= names and "stock" not in names:
        kwargs = {"symbol": stock, "indicator": statement}
    elif {"stock", "symbol"} <= names and "indicator" not in names:
        kwargs = {"stock": stock, "symbol": statement}
    else:
        raise ValueError("unrecognized Sina statement signature")
    inspect.signature(fn).bind(**kwargs)
    return kwargs


def call_sina_statement(fn: Callable, stock: str, statement: str) -> Any:
    return fn(**sina_statement_kwargs(fn, stock, statement))
