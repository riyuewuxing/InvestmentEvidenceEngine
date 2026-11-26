import pytest

from investment_evidence_engine.sina_statement_adapter import call_sina_statement


def test_known_signatures_bind_correct_semantics():
    def legacy(stock, symbol):
        return stock, symbol

    def current(stock, indicator):
        return stock, indicator

    def renamed(symbol, indicator):
        return symbol, indicator

    for fn in (legacy, current, renamed):
        assert call_sina_statement(fn, "sh600000", "利润表") == ("sh600000", "利润表")


def test_no_blind_retry_or_unknown_signature():
    calls = []

    def broken(stock, indicator):
        calls.append(stock)
        raise TypeError("provider internals")

    with pytest.raises(TypeError):
        call_sina_statement(broken, "sh600000", "利润表")
    assert len(calls) == 1
    with pytest.raises(ValueError):
        call_sina_statement(lambda *args, **kwargs: None, "sh600000", "利润表")
    with pytest.raises(ValueError):
        call_sina_statement(broken, "600000", "利润表")
