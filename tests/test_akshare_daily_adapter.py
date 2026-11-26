from types import SimpleNamespace

import pytest

from investment_evidence_engine.akshare_daily_adapter import call_akshare_daily, call_sina_stock_daily


def test_current_endpoint_preferred_and_legacy_only_when_absent():
    calls = []

    def modern(**kw):
        calls.append(("modern", kw))
        return "new"

    def old(**kw):
        calls.append(("old", kw))
        return "old"

    params = {"symbol": "600000", "period": "daily", "adjust": ""}
    assert call_akshare_daily(SimpleNamespace(stock_zh_a_hist_em=modern, stock_zh_a_hist=old), **params) == "new"
    assert call_akshare_daily(SimpleNamespace(stock_zh_a_hist=old), **params) == "old"
    assert calls == [("modern", params), ("old", params)]


def test_provider_error_not_retried_through_old_name():
    def fail(**kw):
        raise TimeoutError("source unavailable")

    def old(**kw):
        pytest.fail("must not retry a live failure")

    with pytest.raises(TimeoutError):
        call_akshare_daily(SimpleNamespace(stock_zh_a_hist_em=fail, stock_zh_a_hist=old), symbol="600000")
    with pytest.raises(ValueError):
        call_akshare_daily(SimpleNamespace(), symbol="600000")


def test_sina_current_name_with_period_and_legacy_without_period():
    calls = []
    def current(**kw):
        calls.append(("current", kw))
        return "current"
    def legacy(**kw):
        calls.append(("legacy", kw))
        return "legacy"
    params = {"symbol": "sh600000", "start_date": "20250101",
              "end_date": "20250201", "adjust": ""}
    assert call_sina_stock_daily(SimpleNamespace(stock_zh_a_hist_sina=current,
                                                 stock_zh_a_daily=legacy), **params) == "current"
    assert call_sina_stock_daily(SimpleNamespace(stock_zh_a_daily=legacy), **params) == "legacy"
    assert calls == [("current", params | {"period": "daily"}), ("legacy", params)]


def test_sina_provider_failure_not_retried_or_relabelled():
    def fail(**kw):
        raise TimeoutError("source unavailable")
    def forbidden(**kw):
        pytest.fail("must not retry or switch vendor")
    with pytest.raises(TimeoutError):
        call_sina_stock_daily(SimpleNamespace(stock_zh_a_hist_sina=fail,
                            stock_zh_a_daily=forbidden), symbol="sh600000")
    with pytest.raises(ValueError, match="SINA_STOCK_DAILY_ENDPOINT_UNAVAILABLE"):
        call_sina_stock_daily(SimpleNamespace(stock_zh_a_hist_em=forbidden), symbol="sh600000")
