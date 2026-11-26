from types import SimpleNamespace

import pytest

from investment_evidence_engine.akshare_daily_adapter import call_akshare_daily


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
