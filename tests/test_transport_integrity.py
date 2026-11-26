import hashlib

import pytest

from investment_evidence_engine.transport_integrity import (
    observe_artifact_file,
    read_contract_bytes,
    read_verified_artifact,
    request_chain_errors,
    result_transport_errors,
    safe_artifact_path,
    safe_operation_id,
)


def ops():
    return [
        {"operation_id": "first", "parameters": {}},
        {"operation_id": "second", "parameters": {"depends_on_operation_ids": ["first"]}},
    ]


def results(first="PASS", second="PASS"):
    return [
        {"operation_id": "first", "status": first, "exit_code": 0, "artifacts": []},
        {"operation_id": "second", "status": second, "exit_code": 0,
         "artifacts": [{"path": "research.json"}]},
    ]


@pytest.mark.parametrize("path", ["../a", "/a", "a/../b", "a//b", "a\\b", "C:a",
                                 "run_manifest.json", "a/execution_result.json", "a.", "NUL.txt", "a\n"])
def test_portable_artifact_paths(path):
    assert not safe_artifact_path(path)


def test_good_transport_only():
    assert safe_operation_id("research-v2.1")
    assert safe_artifact_path("subdir/research-v2.1.json")
    assert not request_chain_errors(ops())
    assert not result_transport_errors(ops(), results(), "PASS")


@pytest.mark.parametrize("first,second,overall,expected", [
    ("BLOCK", "PASS", "BLOCK", "UNUSABLE_UPSTREAM_PROMOTED:second"),
    ("WARN", "PASS", "WARN", "UPSTREAM_WARNING_LOST:second"),
    ("PASS", "PASS", "WARN", "OVERALL_STATUS_MISMATCH"),
])
def test_no_status_promotion(first, second, overall, expected):
    assert expected in result_transport_errors(ops(), results(first, second), overall)


def test_warn_is_research_usable_but_not_promoted():
    assert not result_transport_errors(ops(), results("WARN", "WARN"), "WARN")


def test_reordered_or_incomplete_result():
    assert "OPERATION_ORDER_OR_COVERAGE_MISMATCH" in result_transport_errors(
        ops(), list(reversed(results())), "PASS")


@pytest.mark.parametrize("path", ["Research.JSON", "research.json/sub.json"])
def test_duplicate_and_prefix_alias(path):
    out = results()
    out[0]["artifacts"] = [{"path": path}]
    assert any(x.startswith("DUPLICATE_OR_ALIASED_ARTIFACT_PATH:")
               for x in result_transport_errors(ops(), out, "PASS"))


def test_success_cannot_hide_errors_or_missing_artifacts():
    out = results()
    out[1]["errors"] = ["source failure"]
    out[1]["artifacts"] = []
    problems = result_transport_errors(ops(), out, "PASS")
    assert "SUCCESS_STATUS_CONFLICT:second" in problems
    assert "NO_OBSERVABLE_ARTIFACTS" in problems


@pytest.mark.parametrize("dependencies", [["second"], ["first", "first"], [1], "first"])
def test_invalid_dependency_graph(dependencies):
    requested = ops()
    requested[1]["parameters"]["depends_on_operation_ids"] = dependencies
    assert "INVALID_OPERATION_DEPENDENCIES:second" in request_chain_errors(requested)


def test_observe_exact_bytes_and_size(tmp_path):
    body = b"synthetic evidence"
    path = tmp_path / "sub" / "evidence.json"
    path.parent.mkdir()
    path.write_bytes(body)
    assert observe_artifact_file(tmp_path, "sub/evidence.json", len(body)) == (
        hashlib.sha256(body).hexdigest(), len(body))
    with pytest.raises(ValueError, match="SIZE_MISMATCH"):
        observe_artifact_file(tmp_path, "sub/evidence.json", len(body) + 1)
    with pytest.raises(ValueError, match="OVERSIZED"):
        observe_artifact_file(tmp_path, "sub/evidence.json", max_bytes=5)
    with pytest.raises(ValueError, match="NOT_OBSERVED"):
        observe_artifact_file(tmp_path, "missing.json")


def test_observation_rejects_symlink_even_inside_root(tmp_path):
    target = tmp_path / "evidence.json"
    target.write_bytes(b"valid")
    alias = tmp_path / "alias.json"
    try:
        alias.symlink_to(target)
    except OSError:
        pytest.skip("symbolic links not available")
    with pytest.raises(ValueError, match="SYMLINK_FORBIDDEN"):
        observe_artifact_file(tmp_path, "alias.json")
    with pytest.raises(ValueError, match="CONTRACT_FILE_INVALID"):
        read_contract_bytes(alias)


def test_observation_rejects_symlink_parent(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "data.json").write_bytes(b"ok")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links not available")
    with pytest.raises(ValueError, match="SYMLINK_FORBIDDEN"):
        observe_artifact_file(tmp_path, "alias/data.json")


def test_bounded_contract_read(tmp_path):
    path = tmp_path / "request.json"
    path.write_bytes(b"{}")
    assert read_contract_bytes(path) == b"{}"
    path.write_bytes(b"")
    with pytest.raises(ValueError, match="CONTRACT_FILE_INVALID"):
        read_contract_bytes(path)


def test_parse_uses_same_verified_bytes_not_a_second_read(tmp_path):
    path = tmp_path / "artifact.json"
    body = b'{"measurement":1}'
    path.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    verified = read_verified_artifact(tmp_path, "artifact.json", digest, len(body))
    path.write_bytes(body.replace(b"1", b"2"))
    assert verified == body
    with pytest.raises(ValueError, match="HASH_OR_SIZE_MISMATCH"):
        read_verified_artifact(tmp_path, "artifact.json", digest, len(body))


@pytest.mark.parametrize("size,digest", [(0, "a"*64), (True, "a"*64), (2, "a"*63)])
def test_verified_artifact_rejects_invalid_expectations(tmp_path, size, digest):
    (tmp_path / "artifact.json").write_bytes(b"{}")
    with pytest.raises(ValueError):
        read_verified_artifact(tmp_path, "artifact.json", digest, size)


def test_verified_artifact_rejects_symlink_parent(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    body = b"{}"
    (real / "artifact.json").write_bytes(body)
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links not available")
    with pytest.raises(ValueError, match="SYMLINK_FORBIDDEN"):
        read_verified_artifact(tmp_path, "alias/artifact.json", hashlib.sha256(body).hexdigest(), len(body))
