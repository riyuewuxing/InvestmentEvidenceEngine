from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 4.0

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("attempts must be >= 1")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays must be non-negative")

    def delay_for_attempt(self, attempt_number: int) -> float:
        if attempt_number < 1:
            raise ValueError("attempt_number must be >= 1")
        return min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2 ** (attempt_number - 1)),
        )


def retry_call(
    function: Callable[[], T],
    *,
    policy: RetryPolicy = RetryPolicy(),
    retry_if: Callable[[Exception], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[T, list[str]]:
    failures: list[str] = []
    for attempt in range(1, policy.attempts + 1):
        try:
            return function(), failures
        except Exception as exc:
            failures.append(f"attempt={attempt}:{type(exc).__name__}:{exc}")
            if attempt >= policy.attempts or (retry_if is not None and not retry_if(exc)):
                raise
            delay = policy.delay_for_attempt(attempt)
            if delay:
                sleep(delay)
    raise RuntimeError("unreachable retry state")
