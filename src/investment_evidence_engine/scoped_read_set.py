"""One lazy read per named observation in a bounded research/request scope.

No persistent cache, network, account identity or evidence admission. Callers
create a fresh instance for each new request, and explicitly bind its lifetime.
A failed observation remains failed within that scope; a new scope may retry.
"""
from __future__ import annotations

from collections.abc import Callable, Hashable
from threading import RLock
from typing import Any, TypeVar, cast

T = TypeVar("T")


class ScopedReadSet:
    def __init__(self) -> None:
        self._values: dict[Hashable, Any] = {}
        self._failures: dict[Hashable, Exception] = {}
        self._reading: set[Hashable] = set()
        self._lock = RLock()

    def read(self, key: Hashable, loader: Callable[[], T]) -> T:
        with self._lock:
            if key in self._values:
                return cast(T, self._values[key])
            if key in self._failures:
                raise self._failures[key]
            if key in self._reading:
                raise RuntimeError("RECURSIVE_OBSERVATION")
            self._reading.add(key)
            try:
                value = loader()
                self._values[key] = value
                return value
            except Exception as exc:
                self._failures[key] = exc
                raise
            finally:
                self._reading.discard(key)

    def peek(self, key: Hashable) -> Any | None:
        """Return a successful read if present; never invoke a loader."""
        with self._lock:
            return self._values.get(key)
