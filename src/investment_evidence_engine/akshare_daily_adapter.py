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


def call_sina_stock_daily(ak: Any, **kwargs: Any) -> Any:
    """Only Sina-family aliases, not fallback to a different vendor."""
    modern = getattr(ak, "stock_zh_a_hist_sina", None)
    if callable(modern):
        return modern(period="daily", **kwargs)
    legacy = getattr(ak, "stock_zh_a_daily", None)
    if callable(legacy):
        return legacy(**kwargs)
    raise ValueError("SINA_STOCK_DAILY_ENDPOINT_UNAVAILABLE")
