"""Resolve known AKShare daily-history endpoint rename before a single call."""
from __future__ import annotations

from typing import Any


def call_akshare_daily(ak: Any, **kwargs: Any) -> Any:
    for name in ("stock_zh_a_hist_em", "stock_zh_a_hist"):
        fn = getattr(ak, name, None)
        if callable(fn):
            # No fallback on exceptions from a real network call.
            return fn(**kwargs)
    raise ValueError("AKShare daily-history endpoint unavailable")
