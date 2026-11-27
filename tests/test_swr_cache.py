import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from investment_evidence_engine import swr_cache
from investment_evidence_engine.swr_cache import SCHEMA, SwrCache


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(swr_cache.time, "time", lambda: 1000.)
    return SwrCache(tmp_path)


def test_valid_round_trip_and_scope_binding(cache, tmp_path):
    cache.write("scope-a", {"observations": 0})
    assert cache.read("scope-a", stale_ttl_sec=10).payload == {"observations": 0}
    cold = SwrCache(tmp_path)
    assert cold.read("scope-a", stale_ttl_sec=10).cache_state == "disk"
    cache._path("scope-b").write_bytes(cache._path("scope-a").read_bytes())
    assert cold.read("scope-b", stale_ttl_sec=10) is None


@pytest.mark.parametrize("clock", [1001, "999", None, False, 0, -1, float("nan"), float("inf"), 10**400])
def test_bad_persisted_timestamp_is_miss(cache, clock):
    cache._dir.mkdir(parents=True)
    cache._path("x").write_text(json.dumps({"schema": SCHEMA,
        "key_sha256": cache._digest("x"), "written_at": clock, "payload": {"old": True}}))
    assert cache.read("x", stale_ttl_sec=10) is None


def test_clock_rollback_invalidates_memory_and_disk(cache, monkeypatch):
    cache.write("x", {"old": True})
    monkeypatch.setattr(swr_cache.time, "time", lambda: 999.)
    assert cache.read("x", stale_ttl_sec=10) is None
    assert cache.get_or_load("x", lambda: {"new": True}, fresh_ttl_sec=5, stale_ttl_sec=10) == ({"new": True}, "miss", 0.)


def test_legacy_and_nonserializable_values_not_reused(cache):
    cache._dir.mkdir(parents=True)
    cache._path("x").write_text(json.dumps({"written_at": 999, "payload": "legacy"}))
    assert cache.read("x", stale_ttl_sec=10) is None
    cache.write("x", {"bad": float("nan")})
    assert cache.read("x", stale_ttl_sec=10) is None


def test_atomic_concurrent_writes_leave_no_shared_temporary_file(cache, tmp_path):
    other = SwrCache(tmp_path)
    values = [{"id": i, "data": [i] * 1000} for i in range(16)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda v: (cache if v["id"] % 2 else other).write("x", v), values))
    result = SwrCache(tmp_path).read("x", stale_ttl_sec=10)
    assert result is not None and result.payload in values
    assert not list(cache._dir.glob("*.tmp"))
