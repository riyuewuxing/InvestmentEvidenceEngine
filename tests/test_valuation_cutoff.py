import hashlib
import json
from datetime import date

import pandas as pd
import pytest

from investment_evidence_engine.contracts import ExecutionOperation
from investment_evidence_engine.dispatch import run_operation
from investment_evidence_engine.providers import AKShareResearchProvider
from investment_evidence_engine.workers import WorkerContext


def _run(tmp_path, monkeypatch, frame, cutoff="2025-01-03", subjects=None):
    monkeypatch.setattr(AKShareResearchProvider, "get_valuation_history", lambda self, symbol: frame)
    op = ExecutionOperation(
        operation_id="valuation",
        kind="VALUATION_HISTORY",
        parameters={
            "subject_ids": ["600519"] if subjects is None else subjects,
            "as_of": cutoff,
        },
    )
    context = WorkerContext(output_dir=tmp_path)
    return run_operation(op, context), context


def test_excludes_later_rows_and_preserves_unknown_vintage(tmp_path, monkeypatch):
    frame = pd.DataFrame({
        "数据日期": [date(2025, 1, 6), date(2025, 1, 3), date(2025, 1, 2)],
        "PE(TTM)": [9999, -5, 15],
    })
    result, context = _run(tmp_path, monkeypatch, frame)
    assert result.status == "WARN"
    assert result.decision_authority is False
    assert result.metrics == {"rows": 2, "excluded_after_cutoff": 1}
    payload = context.payloads["valuation"]
    assert payload["pit_safe"] is False
    assert payload["historical_vintage_verified"] is False
    assert payload["latest_data_date"] == "2025-01-03"
    assert [row["数据日期"] for row in payload["records"]] == ["2025-01-02", "2025-01-03"]
    assert [row["PE(TTM)"] for row in payload["records"]] == [15, -5]
    raw = (tmp_path / "valuation.json").read_bytes()
    assert result.artifacts[0].sha256 == hashlib.sha256(raw).hexdigest()
    assert json.loads(raw) == payload
    assert all(row["PE(TTM)"] != 9999 for row in json.loads(raw)["records"])


@pytest.mark.parametrize(("frame", "reason"), [
    (pd.DataFrame({"PE(TTM)": [15]}), "VALUATION_DATE_COLUMN_MISSING_OR_AMBIGUOUS"),
    (pd.DataFrame({"date": ["2025-01-02"], "数据日期": ["2025-01-02"]}),
     "VALUATION_DATE_COLUMN_MISSING_OR_AMBIGUOUS"),
    (pd.DataFrame({"数据日期": ["not-a-date", "2025-01-02"]}), "VALUATION_INVALID_PROVIDER_DATE"),
    (pd.DataFrame({"数据日期": [None, "2025-01-02"]}), "VALUATION_INVALID_PROVIDER_DATE"),
    (pd.DataFrame({"数据日期": ["2025-01-06"]}), "VALUATION_NO_ROWS_AT_OR_BEFORE_CUTOFF"),
    (pd.DataFrame({"数据日期": ["2025-01-02", "2025-01-02"], "PE(TTM)": [15, 20]}),
     "VALUATION_DUPLICATE_ELIGIBLE_DATES"),
])
def test_unverifiable_rows_block_without_artifact(tmp_path, monkeypatch, frame, reason):
    result, context = _run(tmp_path, monkeypatch, frame)
    assert result.status == "BLOCK"
    assert result.errors == [reason]
    assert not result.artifacts
    assert not context.payloads
    assert not (tmp_path / "valuation.json").exists()


@pytest.mark.parametrize("subjects", [[], ["600519", "000001"], ["１２３４５６"], ["sh600519"]])
def test_exact_single_subject_required(tmp_path, monkeypatch, subjects):
    result, _ = _run(tmp_path, monkeypatch, pd.DataFrame(), subjects=subjects)
    assert result.errors == ["VALUATION_REQUIRES_ONE_EXACT_SIX_DIGIT_SYMBOL"]


@pytest.mark.parametrize("cutoff", ["2025-01-03T09:30:00+08:00", "20250103", None])
def test_date_only_cutoff_not_silently_truncated(tmp_path, monkeypatch, cutoff):
    result, _ = _run(tmp_path, monkeypatch, pd.DataFrame(), cutoff=cutoff)
    assert result.errors == ["VALUATION_REQUIRES_EXACT_CALENDAR_DATE"]
