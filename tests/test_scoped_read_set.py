from concurrent.futures import ThreadPoolExecutor

import pytest

from investment_evidence_engine import observed_artifact_bytes as observed
from investment_evidence_engine.scoped_read_set import ScopedReadSet


def test_independent_observations_and_new_scope():
    sources = {"a": "v1", "b": "v2"}
    current = ScopedReadSet()
    assert current.peek("a") is None
    assert current.read("a", lambda: sources["a"]) == "v1"
    sources["a"] = "v3"
    assert current.read("b", lambda: sources["b"]) == "v2"
    assert current.read("a", lambda: sources["a"]) == "v1"
    assert ScopedReadSet().read("a", lambda: sources["a"]) == "v3"


def test_failed_scope_does_not_switch_mid_request():
    scope = ScopedReadSet()
    def unavailable():
        raise OSError("synthetic unavailable")
    with pytest.raises(OSError):
        scope.read("a", unavailable)
    with pytest.raises(OSError):
        scope.read("a", lambda: "later success")
    assert scope.peek("a") is None
    assert scope.read("b", lambda: "independent") == "independent"
    assert ScopedReadSet().read("a", lambda: "new request") == "new request"


def test_concurrent_reads_share_first_observation():
    calls = []
    scope = ScopedReadSet()
    def load():
        calls.append(1)
        return {"observation": 1}
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(lambda _: scope.read("same", load), range(32)))
    assert len(calls) == 1
    assert all(v is values[0] for v in values)


def test_recursion_is_not_a_second_read():
    scope = ScopedReadSet()
    with pytest.raises(RuntimeError, match="RECURSIVE_OBSERVATION"):
        scope.read("a", lambda: scope.read("a", lambda: 2))


def test_named_file_version_binds_exact_bytes_and_names(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.write_bytes(b"a\r\n")
    second.write_bytes(b"b")
    files = {"one": first, "two": second}
    data, version = observed.observe_named_files(files)
    assert data["one"].content == b"a\r\n"
    assert observed.observe_named_files(dict(reversed(list(files.items()))))[1] == version
    assert observed.observe_named_files({"renamed": first, "two": second})[1] != version
    first.write_bytes(b"a\n")
    assert observed.observe_named_files(files)[1] != version
    with pytest.raises(ValueError):
        observed.observe_named_files(files, max_bytes=1)


def test_file_set_rejects_change_after_earlier_member_read(tmp_path, monkeypatch):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    read = observed.observe_file
    def mutate(path, **kwargs):
        if path == second:
            first.write_bytes(b"changed")
        return read(path, **kwargs)
    monkeypatch.setattr(observed, "observe_file", mutate)
    with pytest.raises(ValueError, match="OBSERVATION_FILE_SET_CHANGED"):
        observed.observe_named_files({"a": first, "b": second})


def test_file_set_rejects_ambiguous_labels_duplicate_and_symlink(tmp_path):
    first = tmp_path / "first"
    first.write_bytes(b"a")
    with pytest.raises(ValueError):
        observed.observe_named_files({"a\n": first})
    with pytest.raises(ValueError):
        observed.observe_named_files({"a": first, "b": first})
    link = tmp_path / "link"
    link.symlink_to(first)
    with pytest.raises(ValueError):
        observed.observe_named_files({"a": link})
