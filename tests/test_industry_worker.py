from datetime import date, timedelta

import pandas as pd

from investment_evidence_engine.contracts import ExecutionOperation
from investment_evidence_engine.industry_worker import run_industry_macro
from investment_evidence_engine.providers import AKShareResearchProvider
from investment_evidence_engine.workers import WorkerContext


def _bars(start: date, rows: int = 140) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": start + timedelta(days=index),
                "open": 100 + index * 0.1,
                "high": 101 + index * 0.1,
                "low": 99 + index * 0.1,
                "close": 100.5 + index * 0.1,
                "volume": 100000 + index,
            }
            for index in range(rows)
        ]
    )


def test_industry_macro_returns_public_context_without_investment_advice(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        AKShareResearchProvider,
        "get_company_profile",
        lambda self, symbol: {"所属行业": "白酒"},
    )
    monkeypatch.setattr(
        AKShareResearchProvider,
        "get_index_daily",
        lambda self, index_symbol, start, end: _bars(start),
    )
    monkeypatch.setattr(
        AKShareResearchProvider,
        "get_industry_daily",
        lambda self, industry_name, start, end: _bars(start),
    )
    monkeypatch.setattr(
        AKShareResearchProvider,
        "get_industry_constituents",
        lambda self, industry_name: pd.DataFrame(
            [{"代码": "600519", "名称": "示例"}, {"代码": "000858", "名称": "示例2"}]
        ),
    )
    operation = ExecutionOperation(
        operation_id="industry",
        kind="INDUSTRY_MACRO",
        parameters={"subject_ids": ["600519"], "as_of": "2026-08-24"},
        evidence_domains=["INDUSTRY_MACRO"],
    )
    result = run_industry_macro(operation, WorkerContext(output_dir=tmp_path))
    assert result.status == "PASS"
    assert result.metrics["industry_name"] == "白酒"
    assert result.metrics["constituent_count"] == 2
    payload = (tmp_path / "industry.json").read_text(encoding="utf-8")
    assert '"decision_authority": false' in payload
