import pytest

from investment_evidence_engine.transport_integrity import (
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
