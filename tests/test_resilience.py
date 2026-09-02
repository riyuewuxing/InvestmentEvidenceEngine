import pytest

from investment_evidence_engine.resilience import RetryPolicy, retry_call


def test_retry_call_recovers() -> None:
    attempts = {"count": 0}
    sleeps: list[float] = []

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TimeoutError("temporary")
        return "ok"

    value, failures = retry_call(
        flaky,
        policy=RetryPolicy(attempts=3, base_delay_seconds=0.1, max_delay_seconds=0.2),
        sleep=sleeps.append,
    )
    assert value == "ok"
    assert len(failures) == 2
    assert sleeps == [0.1, 0.2]


def test_retry_call_stops_on_non_retryable() -> None:
    attempts = {"count": 0}

    def fail() -> None:
        attempts["count"] += 1
        raise ValueError("bad input")

    with pytest.raises(ValueError):
        retry_call(
            fail,
            policy=RetryPolicy(attempts=3, base_delay_seconds=0),
            retry_if=lambda exc: isinstance(exc, TimeoutError),
        )
    assert attempts["count"] == 1
