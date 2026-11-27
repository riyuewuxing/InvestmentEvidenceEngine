"""Read-only SWR cache with scoped keys, bounded clocks and atomic disk writes.

Cache data is not evidence authority. Missing, legacy or malformed cache
entries are misses, not fabricated payloads. The caller defines its scope.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_CACHE_BYTES = 32 * 1024 * 1024
SCHEMA = "SWR_CACHE_V2"


@dataclass(frozen=True)
class SwrHit:
    payload: Any
    age_sec: float
    cache_state: str


def _reject_constant(value: str) -> Any:
    raise ValueError(f"invalid JSON constant: {value}")


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate cache JSON key")
        result[key] = value
    return result


def _age(now: float, written_at: Any, ttl: float) -> float | None:
    if type(written_at) not in (int, float) or not 0 < written_at <= now:
        return None
    age = now - written_at
    return age if math.isfinite(age) and 0 <= age <= ttl else None


class SwrCache:
    def __init__(self, root: Path, *, namespace: str = "swr_cache") -> None:
        self._dir = Path(root) / "data" / namespace
        self._mem: dict[str, tuple[float, Any]] = {}
        self._lock = threading.RLock()
        self._inflight: set[str] = set()

    @staticmethod
    def _digest(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self._dir / f"{self._digest(key)[:24]}.json"

    def read(self, key: str, *, stale_ttl_sec: float) -> SwrHit | None:
        now = time.time()
        # Serialize read/hydration with writes within this cache instance.
        with self._lock:
            mem = self._mem.get(key)
            if mem is not None:
                age = _age(now, mem[0], stale_ttl_sec)
                if age is not None:
                    return SwrHit(mem[1], age, "memory")
                self._mem.pop(key, None)
            path = self._path(key)
            try:
                if path.is_symlink() or not path.is_file():
                    return None
                with path.open("rb") as handle:
                    payload = handle.read(MAX_CACHE_BYTES + 1)
                if len(payload) > MAX_CACHE_BYTES:
                    return None
                raw = json.loads(payload, parse_constant=_reject_constant,
                                 object_pairs_hook=_unique_pairs)
                if (not isinstance(raw, dict) or raw.get("schema") != SCHEMA
                        or raw.get("key_sha256") != self._digest(key) or "payload" not in raw
                        or raw["payload"] is None):
                    return None
                age = _age(now, raw.get("written_at"), stale_ttl_sec)
                if age is None:
                    return None
            except (OSError, ValueError, TypeError, OverflowError):
                return None
            self._mem[key] = (float(raw["written_at"]), raw["payload"])
            return SwrHit(raw["payload"], age, "disk")

    def write(self, key: str, payload: Any) -> None:
        if payload is None:
            return
        with self._lock:
            now = time.time()
            try:
                raw = json.dumps({"schema": SCHEMA, "key_sha256": self._digest(key),
                                  "written_at": now, "payload": payload},
                                 ensure_ascii=False, allow_nan=False).encode("utf-8")
            except (TypeError, ValueError, OverflowError):
                return
            if len(raw) > MAX_CACHE_BYTES or _age(now, now, 0) is None:
                return
            self._mem[key] = (now, payload)
            tmp = None
            try:
                self._dir.mkdir(parents=True, exist_ok=True)
                # A unique sibling avoids same-name races across writers/processes.
                with tempfile.NamedTemporaryFile(dir=self._dir, prefix=".swr-", suffix=".tmp",
                                                 delete=False) as handle:
                    tmp = Path(handle.name)
                    handle.write(raw)
                os.replace(tmp, self._path(key))
            except OSError:
                pass
            finally:
                if tmp is not None:
                    try:
                        tmp.unlink(missing_ok=True)
                    except OSError:
                        pass

    def revalidate_async(self, key: str, loader: Callable[[], Any], *,
                         namespace_guard: str = "") -> None:
        with self._lock:
            if key in self._inflight:
                return
            self._inflight.add(key)

        def _run() -> None:
            try:
                payload = loader()
                if payload is not None:
                    self.write(key, payload)
            except Exception:  # best-effort refresh, not evidence admission
                pass
            finally:
                with self._lock:
                    self._inflight.discard(key)

        thread = threading.Thread(target=_run,
            name=f"swr-revalidate-{(namespace_guard or key)[:24]}", daemon=True)
        try:
            thread.start()
        except RuntimeError:
            with self._lock:
                self._inflight.discard(key)

    def get_or_load(self, key: str, loader: Callable[[], Any], *,
                    fresh_ttl_sec: float, stale_ttl_sec: float) -> tuple[Any, str, float]:
        hit = self.read(key, stale_ttl_sec=stale_ttl_sec)
        if hit is not None:
            if hit.age_sec <= fresh_ttl_sec:
                return hit.payload, "fresh", hit.age_sec
            self.revalidate_async(key, loader)
            return hit.payload, "stale_revalidating", hit.age_sec
        payload = loader()
        if payload is not None:
            self.write(key, payload)
        return payload, "miss", 0.0
