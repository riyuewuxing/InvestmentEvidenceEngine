import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from investment_evidence_engine.contracts import ExecutionOperation
from investment_evidence_engine.dispatch import run_operation
from investment_evidence_engine.market_universe_worker import (
    _fetch_sina_pages,
    _sina_adapter,
    _sina_page_count,
)
from investment_evidence_engine.runner import execute_request
from investment_evidence_engine.workers import WorkerContext

AS_OF = "2026-09-02"


class FakeAKShare:
    def __init__(self, *, primary=None, fallback=None, listings=None):
        self.primary = primary
        self.fallback = fallback
        self.listings = listings
        self.primary_calls = 0
        self.fallback_calls = 0
        self.listing_calls = 0

    def stock_zh_a_spot_em(self):
        self.primary_calls += 1
        if isinstance(self.primary, Exception):
            raise self.primary
        return self.primary

    def stock_zh_a_spot(self):
        self.fallback_calls += 1
        if isinstance(self.fallback, Exception):
            raise self.fallback
        return self.fallback

    def stock_zh_a_spot_pages(self):
        self.fallback_calls += 1
        if isinstance(self.fallback, Exception):
            raise self.fallback
        return self.fallback

    def stock_info_a_code_name(self):
        self.listing_calls += 1
        if isinstance(self.listings, Exception):
            raise self.listings
        return self.listings


def _clock() -> datetime:
    return datetime(2026, 9, 2, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def _context(
    tmp_path: Path,
    provider: FakeAKShare,
    *,
    request_as_of: str = AS_OF,
) -> WorkerContext:
    return WorkerContext(
        output_dir=tmp_path,
        providers={"akshare": provider},
        request_as_of=request_as_of,
        clock=_clock,
    )


def _operation(**parameters: object) -> ExecutionOperation:
    return ExecutionOperation(
        operation_id="universe",
        kind="MARKET_UNIVERSE",
        parameters={"as_of": AS_OF, "min_universe_size": 1, **parameters},
        evidence_domains=["MARKET"],
    )


def _rows(*, with_quote_date: bool = True) -> pd.DataFrame:
    rows = [
        {
            "代码": "600519",
            "名称": "贵州茅台",
            "最新价": 1500.0,
            "涨跌幅": 1.2,
            "成交量": 1000,
            "成交额": 1500000,
            "振幅": 2.0,
            "换手率": 0.5,
            "市盈率-动态": 30.0,
            "市净率": 8.0,
            "总市值": 1.8e12,
            "流通市值": 1.8e12,
            "60日涨跌幅": 3.0,
            "年初至今涨跌幅": 5.0,
        },
        {
            "代码": "000001",
            "名称": "平安银行",
            "最新价": 10.0,
            "涨跌幅": -0.5,
            "成交量": 2000,
            "成交额": 20000,
        },
    ]
    if with_quote_date:
        for row in rows:
            row["quote_trade_date"] = AS_OF
    return pd.DataFrame(rows)


def _listings() -> pd.DataFrame:
    return pd.DataFrame({"证券代码": ["600519", "000001"], "证券简称": ["贵州茅台", "平安银行"]})


def test_primary_snapshot_normalizes_and_feeds_opportunity_scan(tmp_path: Path) -> None:
    provider = FakeAKShare(primary=_rows(), listings=_listings())
    context = _context(tmp_path, provider)

    universe = run_operation(
        _operation(min_universe_size=2, market="CN_A", asset_type="STOCK"),
        context,
    )

    assert universe.status == "PASS"
    payload = context.payloads["universe"]
    assert [record["code"] for record in payload["records"]] == ["000001", "600519"]
    assert payload["records"][0]["asset"] == "000001"
    assert payload["volume_unit"] == "shares"
    assert payload["records"][0]["volume"] == 200000
    assert payload["quote_trade_date"] == AS_OF
    assert payload["listing_crosscheck"]["overlap_rows"] == 2
    assert payload["listing_crosscheck"]["name_mismatch_count"] == 0
    assert payload["provider_history"] == [
        {"endpoint": "stock_zh_a_spot_em", "provider": "akshare", "rows": 2, "status": "PASS"}
    ]
    assert provider.primary_calls == 1
    assert provider.fallback_calls == 0

    scan = ExecutionOperation(
        operation_id="scan",
        kind="OPPORTUNITY_SCAN",
        parameters={
            "as_of": AS_OF,
            "depends_on_operation_ids": ["universe"],
            "rules": [{"field": "pct_change", "operator": "GE", "threshold": 0}],
            "ranking_semantics": "RESEARCH_PRIORITY_NOT_RETURN_FORECAST",
            "rule_origin": "USER_PROVIDED_RESEARCH_FILTER",
            "market": "CN_A",
            "asset_type": "STOCK",
        },
    )
    scan_result = run_operation(scan, context)

    assert scan_result.status == "PASS"
    assert context.payloads["scan"]["ranking_semantics"] == "RESEARCH_PRIORITY_NOT_RETURN_FORECAST"
    assert context.payloads["scan"]["input_mode"] == "LIVE_MARKET_UNIVERSE"
    assert context.completed_operations["universe"] == {
        "kind": "MARKET_UNIVERSE",
        "status": "PASS",
        "as_of": AS_OF,
        "market": "CN_A",
        "asset_type": "STOCK",
    }
    assert context.payloads["scan"]["candidates"][0]["code"] == "600519"
    assert "forecast" not in context.payloads["universe"]
    assert "advice" not in context.payloads["universe"]


def test_live_scan_rejects_market_asset_type_mismatch_with_universe(tmp_path: Path) -> None:
    provider = FakeAKShare(primary=_rows(), listings=_listings())
    context = _context(tmp_path, provider)
    universe = run_operation(
        _operation(min_universe_size=2, market="CN_A", asset_type="STOCK"),
        context,
    )
    assert universe.status == "PASS"
    scan = ExecutionOperation(
        operation_id="scan",
        kind="OPPORTUNITY_SCAN",
        parameters={
            "as_of": AS_OF,
            "depends_on_operation_ids": ["universe"],
            "rules": [{"field": "pct_change", "operator": "GE", "threshold": 0}],
            "market": "US",
            "asset_type": "STOCK",
        },
    )

    result = run_operation(scan, context)

    assert result.status == "BLOCK"
    assert result.errors == ["OPPORTUNITY_SCAN_DEPENDENCY_SCOPE_INVALID"]


@pytest.mark.parametrize(
    "key, value",
    [
        ("ranking_semantics", "BUY_SIGNAL"),
        ("rule_origin", "AUTOMATED_ADVICE"),
    ],
)
def test_live_scan_rejects_non_research_semantics(
    key: str, value: str, tmp_path: Path
) -> None:
    provider = FakeAKShare(primary=_rows(), listings=_listings())
    context = _context(tmp_path, provider)
    universe = run_operation(_operation(min_universe_size=2), context)
    assert universe.status == "PASS"
    scan_parameters = {
        "as_of": AS_OF,
        "depends_on_operation_ids": ["universe"],
        "rules": [{"field": "pct_change", "operator": "GE", "threshold": 0}],
        key: value,
    }
    scan = ExecutionOperation(
        operation_id="scan",
        kind="OPPORTUNITY_SCAN",
        parameters=scan_parameters,
    )

    result = run_operation(scan, context)

    assert result.status == "BLOCK"
    assert result.errors == ["OPPORTUNITY_SCAN_SEMANTICS_INVALID"]


def test_unknown_quote_date_is_warn_and_retrieval_time_is_distinct(tmp_path: Path) -> None:
    provider = FakeAKShare(primary=_rows(with_quote_date=False), listings=_listings())
    context = _context(tmp_path, provider)

    result = run_operation(_operation(min_universe_size=2), context)

    assert result.status == "WARN"
    operation_payload = context.payloads["universe"]
    assert operation_payload["quote_trade_date"] is None
    assert operation_payload["retrieved_at"].endswith("+00:00")
    assert operation_payload["retrieved_at"][:10] == AS_OF
    assert "MARKET_UNIVERSE_QUOTE_DATE_UNVERIFIED" in result.warnings


def test_unsupported_market_universe_market_blocks_before_provider_call(tmp_path: Path) -> None:
    provider = FakeAKShare(primary=_rows(), listings=_listings())

    result = run_operation(
        _operation(market="US"),
        _context(tmp_path, provider),
    )

    assert result.status == "BLOCK"
    assert result.errors == ["MARKET_UNIVERSE_SCOPE_UNSUPPORTED"]
    assert provider.primary_calls == 0
    assert provider.fallback_calls == 0
    assert provider.listing_calls == 0


def test_market_universe_defaults_to_private_producer_market_asset_type(tmp_path: Path) -> None:
    provider = FakeAKShare(primary=_rows(), listings=_listings())
    context = _context(tmp_path, provider)

    result = run_operation(_operation(min_universe_size=2), context)

    assert result.status == "PASS"
    payload = context.payloads["universe"]
    assert payload["market"] == "CN_A"
    assert payload["asset_type"] == "STOCK"


def test_primary_failure_uses_one_sina_fallback_and_warns(tmp_path: Path) -> None:
    sina_rows = pd.DataFrame(
        {
            "代码": ["SH600519", "sz000001", "BJ430017", "880001"],
            "名称": ["贵州茅台", "平安银行", "星昊医药", "北交旧股"],
            "最新价": [1500.0, 10.0, 20.0, 8.0],
            "涨跌幅": [1.2, -0.5, 0.2, 0.1],
            "成交量": [1000, 2000, 3000, 4000],
            "成交额": [1500000, 20000, 60000, 32000],
            "市盈率-动态": [30.0, 7.0, 20.0, 15.0],
            "市净率": [8.0, 0.7, 2.0, 1.5],
            "时间戳": ["10:00:00", "10:00:00", "10:00:00", "10:00:00"],
        }
    )
    provider = FakeAKShare(
        primary=RuntimeError("eastmoney down"),
        fallback=sina_rows,
        listings=pd.DataFrame({"code": ["600519", "000001", "430017", "880001"]}),
    )

    context = _context(tmp_path, provider)
    result = run_operation(_operation(min_universe_size=2), context)

    assert result.status == "WARN"
    assert provider.primary_calls == 1
    assert provider.fallback_calls == 1
    assert any("MARKET_UNIVERSE_PRIMARY_FAILED" in warning for warning in result.warnings)
    assert result.metrics["provider_attempt_count"] == 2
    assert result.metrics["fallback_used"] is True
    assert context.payloads["universe"]["provider_history"][1]["adapter_contract"] == (
        "provider.stock_zh_a_spot_pages"
    )
    assert context.payloads["universe"]["provider_history"][1]["adapter_version"] == "TEST_OR_INJECTED"
    records = context_payload(tmp_path)["records"]
    assert next(record for record in records if record["code"] == "600519")["volume"] == 1000
    assert "880001" in {record["code"] for record in records}


class _FakeSinaResponse:
    def __init__(self, text: str, error: Exception | None = None):
        self.text = text
        self.error = error

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error


def _sina_raw_row(code: str, name: str) -> list[str]:
    return [
        f"sh{code}",
        code,
        name,
        "10.5",
        "0.2",
        "1.9",
        "10.4",
        "10.6",
        "10.3",
        "10.2",
        "10.8",
        "10.1",
        "1000",
        "20000",
        "10:00:00",
        "20.0",
        "1.5",
        "1000000",
        "500000",
        "2.0",
    ]


def test_sina_paged_bad_json_retries_then_concatenates_all_pages() -> None:
    attempts: dict[int, int] = {}

    def get(url: str, *, params=None, timeout=None):
        assert timeout == 10
        if params is None:
            return _FakeSinaResponse("160")
        page = int(params["page"])
        attempts[page] = attempts.get(page, 0) + 1
        if page == 1 and attempts[page] == 1:
            return _FakeSinaResponse("not-json")
        rows = [
            _sina_raw_row(f"{600000 + (page - 1) * 80 + index:06d}", f"name-{page}-{index}")
            for index in range(80)
        ]
        return _FakeSinaResponse(json.dumps(rows))

    frame = _fetch_sina_pages(
        get=get,
        decode=json.loads,
        count_url="count",
        data_url="data",
        payload={"page": "1", "num": "80"},
    )

    assert len(frame) == 160
    assert list(frame["code"].head(1)) == ["600000"]
    assert list(frame["code"].tail(1)) == ["600159"]
    assert attempts == {1: 2, 2: 1}


def test_sina_page_count_retains_expected_total_rows() -> None:
    plan = _sina_page_count("5554")

    assert plan.expected_total_rows == 5554
    assert plan.page_count == 70


def test_sina_paged_short_non_final_page_fails_closed() -> None:
    def get(url: str, *, params=None, timeout=None):
        assert timeout == 10
        if params is None:
            return _FakeSinaResponse("160")
        return _FakeSinaResponse(json.dumps([_sina_raw_row(f"{600000 + index:06d}", "name") for index in range(79)]))

    with pytest.raises(RuntimeError, match="Sina page 1 expected 80 rows, got 79"):
        _fetch_sina_pages(
            get=get,
            decode=json.loads,
            count_url="count",
            data_url="data",
            payload={"page": "1", "num": "80"},
        )


def test_sina_paged_short_final_page_fails_closed_and_count_is_not_silently_adjusted() -> None:
    def get(url: str, *, params=None, timeout=None):
        assert timeout == 10
        if params is None:
            return _FakeSinaResponse("114")
        page = int(params["page"])
        row_count = 80 if page == 1 else 33
        return _FakeSinaResponse(
            json.dumps([_sina_raw_row(f"{600000 + index:06d}", "name") for index in range(row_count)])
        )

    with pytest.raises(RuntimeError, match="Sina page 2 expected 34 rows, got 33"):
        _fetch_sina_pages(
            get=get,
            decode=json.loads,
            count_url="count",
            data_url="data",
            payload={"page": "1", "num": "80"},
        )


def test_sina_paged_duplicate_code_fails_closed() -> None:
    page_one = [_sina_raw_row(f"{600000 + index:06d}", "name") for index in range(80)]
    page_two = [_sina_raw_row(f"{600000 + index:06d}", "name") for index in range(80)]

    def get(url: str, *, params=None, timeout=None):
        assert timeout == 10
        if params is None:
            return _FakeSinaResponse("160")
        return _FakeSinaResponse(json.dumps(page_one if params["page"] == "1" else page_two))

    with pytest.raises(RuntimeError, match="Sina duplicate A-share code"):
        _fetch_sina_pages(
            get=get,
            decode=json.loads,
            count_url="count",
            data_url="data",
            payload={"page": "1", "num": "80"},
        )


def test_sina_adapter_requires_expected_internal_contract() -> None:
    class MissingContract:
        pass

    with pytest.raises(RuntimeError, match="AKShare Sina adapter contract unavailable"):
        _sina_adapter(MissingContract())


def test_sina_adapter_contract_failure_is_structured_block(tmp_path: Path, monkeypatch) -> None:
    import investment_evidence_engine.market_universe_worker as worker

    def broken_adapter():
        raise RuntimeError("AKShare Sina adapter contract unavailable")

    monkeypatch.setattr(worker, "_sina_adapter", broken_adapter)
    provider = FakeAKShare(primary=RuntimeError("eastmoney down"), listings=_listings())
    context = _context(tmp_path, provider)

    result = run_operation(_operation(min_universe_size=1), context)

    assert result.status == "BLOCK"
    assert "MARKET_UNIVERSE_NO_SNAPSHOT" in result.errors
    assert context.payloads["universe"]["provider_history"][-1]["status"] == "BLOCK"


def test_sina_paged_consecutive_bad_json_fails_closed_after_three_attempts() -> None:
    page_attempts = 0

    def get(url: str, *, params=None, timeout=None):
        nonlocal page_attempts
        assert timeout == 10
        if params is None:
            return _FakeSinaResponse("80")
        page_attempts += 1
        return _FakeSinaResponse("not-json")

    with pytest.raises(RuntimeError, match="Sina page 1 failed after 3 attempts"):
        _fetch_sina_pages(
            get=get,
            decode=json.loads,
            count_url="count",
            data_url="data",
            payload={"page": "1", "num": "80"},
        )

    assert page_attempts == 3


def test_sina_paged_http_failure_retries_then_succeeds() -> None:
    attempts = 0

    def get(url: str, *, params=None, timeout=None):
        nonlocal attempts
        assert timeout == 10
        if params is None:
            return _FakeSinaResponse("80")
        attempts += 1
        if attempts < 3:
            return _FakeSinaResponse("", error=ConnectionError("upstream unavailable"))
        return _FakeSinaResponse(
            json.dumps([_sina_raw_row(f"{600000 + index:06d}", "贵州茅台") for index in range(80)])
        )

    frame = _fetch_sina_pages(
        get=get,
        decode=json.loads,
        count_url="count",
        data_url="data",
        payload={"page": "1", "num": "80"},
    )

    assert len(frame) == 80
    assert attempts == 3


def test_all_snapshot_providers_failed_blocks(tmp_path: Path) -> None:
    provider = FakeAKShare(primary=RuntimeError("eastmoney down"), fallback=RuntimeError("sina down"))

    result = run_operation(_operation(), _context(tmp_path, provider))

    assert result.status == "BLOCK"
    assert "MARKET_UNIVERSE_NO_SNAPSHOT" in result.errors
    assert provider.primary_calls == 1
    assert provider.fallback_calls == 1


def test_warn_dependency_propagates_compact_evidence_to_scan_artifact(tmp_path: Path) -> None:
    provider = FakeAKShare(primary=_rows(with_quote_date=False), listings=RuntimeError("listing down"))
    context = _context(tmp_path, provider)
    universe = run_operation(_operation(min_universe_size=2), context)
    assert universe.status == "WARN"

    scan = ExecutionOperation(
        operation_id="scan-warn",
        kind="OPPORTUNITY_SCAN",
        parameters={
            "as_of": AS_OF,
            "depends_on_operation_ids": ["universe"],
            "rules": [{"field": "pct_change", "operator": "GE", "threshold": 0}],
        },
    )
    result = run_operation(scan, context)

    assert result.status == "WARN"
    assert result.warnings == ["OPPORTUNITY_SCAN_DEPENDENCY_WARN"]
    evidence = context.payloads["scan-warn"]["dependency_evidence"]
    assert evidence == {
        "operation_id": "universe",
        "kind": "MARKET_UNIVERSE",
        "status": "WARN",
        "as_of": AS_OF,
        "market": "CN_A",
        "asset_type": "STOCK",
        "source": "public_market_data",
        "provider": "akshare",
        "primary_provider": "akshare_em",
        "quote_trade_date_status": "UNKNOWN",
        "listing_crosscheck": {"status": "UNAVAILABLE"},
        "quality_flags": ["MARKET_UNIVERSE_QUOTE_DATE_UNVERIFIED"],
        "warnings": [
            "MARKET_UNIVERSE_LISTING_CROSSCHECK_UNAVAILABLE",
            "MARKET_UNIVERSE_QUOTE_DATE_UNVERIFIED",
        ],
    }
    assert "records" not in evidence
    assert result.artifacts[0].path == "scan-warn.json"
    assert (tmp_path / "scan-warn.json").exists()


def test_historical_as_of_blocks_before_provider_call(tmp_path: Path) -> None:
    provider = FakeAKShare(primary=_rows(), listings=_listings())

    result = run_operation(
        _operation(as_of="2026-09-01"),
        _context(tmp_path, provider, request_as_of="2026-09-01"),
    )

    assert result.status == "BLOCK"
    assert "MARKET_UNIVERSE_HISTORICAL_SNAPSHOT_UNSUPPORTED" in result.errors
    assert provider.primary_calls == 0
    assert provider.fallback_calls == 0
    assert provider.listing_calls == 0


def test_invalid_and_duplicate_codes_are_excluded_and_counted(tmp_path: Path) -> None:
    rows = pd.concat(
        [
            _rows().iloc[[0]],
            _rows().iloc[[0]],
            pd.DataFrame(
                [
                    {"代码": "ABC", "名称": "bad", "最新价": 1, "涨跌幅": 0, "成交量": 1, "成交额": 1},
                    {"代码": "399001", "名称": "index", "最新价": 1, "涨跌幅": 0, "成交量": 1, "成交额": 1},
                ]
            ),
        ],
        ignore_index=True,
    )
    provider = FakeAKShare(primary=rows, listings=_listings())
    context = _context(tmp_path, provider)

    result = run_operation(_operation(), context)

    assert result.status == "WARN"
    assert result.metrics["duplicate_row_count"] == 1
    assert result.metrics["invalid_row_count"] == 2
    assert result.metrics["row_count"] == 1
    assert "MARKET_UNIVERSE_ROWS_FILTERED" in result.warnings


def test_universe_below_minimum_blocks(tmp_path: Path) -> None:
    provider = FakeAKShare(primary=_rows().iloc[[0]], listings=_listings())

    result = run_operation(_operation(min_universe_size=2), _context(tmp_path, provider))

    assert result.status == "BLOCK"
    assert any(error.startswith("MARKET_UNIVERSE_BELOW_MINIMUM:") for error in result.errors)


def test_listing_crosscheck_failure_warns_without_blocking_snapshot(tmp_path: Path) -> None:
    provider = FakeAKShare(primary=_rows(), listings=RuntimeError("listing unavailable"))

    result = run_operation(_operation(min_universe_size=2), _context(tmp_path, provider))

    assert result.status == "WARN"
    assert "MARKET_UNIVERSE_LISTING_CROSSCHECK_UNAVAILABLE" in result.warnings
    assert result.metrics["row_count"] == 2


def test_listing_name_mismatch_is_bounded_warning(tmp_path: Path) -> None:
    listings = _listings()
    listings.loc[0, "证券简称"] = "贵州茅台（旧名）"
    provider = FakeAKShare(primary=_rows(), listings=listings)
    context = _context(tmp_path, provider)

    result = run_operation(_operation(min_universe_size=2), context)

    assert result.status == "WARN"
    crosscheck = context.payloads["universe"]["listing_crosscheck"]
    assert crosscheck["name_mismatch_count"] == 1
    assert crosscheck["name_mismatch_sample"] == ["600519"]
    assert "MARKET_UNIVERSE_LISTING_NAME_MISMATCH" in result.warnings


def test_default_minimum_universe_size_is_production_sized(tmp_path: Path) -> None:
    provider = FakeAKShare(primary=_rows(), listings=_listings())

    result = run_operation(
        ExecutionOperation(
            operation_id="universe",
            kind="MARKET_UNIVERSE",
            parameters={"as_of": AS_OF},
        ),
        _context(tmp_path, provider),
    )

    assert result.status == "BLOCK"
    assert result.metrics["min_universe_size"] >= 1000


def test_akshare_unavailable_is_structured_block_with_artifact(tmp_path: Path, monkeypatch) -> None:
    import investment_evidence_engine.market_universe_worker as worker

    def unavailable(_context):
        raise ImportError("akshare missing")

    monkeypatch.setattr(worker, "_provider", unavailable)
    result = run_operation(
        _operation(),
        WorkerContext(output_dir=tmp_path, request_as_of=AS_OF, clock=_clock),
    )

    assert result.status == "BLOCK"
    assert result.errors == ["MARKET_UNIVERSE_PROVIDER_UNAVAILABLE"]
    assert result.artifacts[0].path == "universe.json"


def test_request_as_of_is_authoritative_in_runner(tmp_path: Path, monkeypatch) -> None:
    provider = FakeAKShare(primary=_rows(), listings=_listings())
    import investment_evidence_engine.market_universe_worker as worker

    monkeypatch.setattr(worker, "_provider", lambda _context: provider)
    request = {
        "schema_version": "1.0",
        "job_id": "job-1",
        "trace_id": "trace-1",
        "subject_repo": "riyuewuxing/touzizhuanjia",
        "subject_commit": "a" * 40,
        "as_of": AS_OF,
        "operations": [_operation(as_of="2026-09-01").model_dump(mode="json")],
        "private_data_included": False,
        "decision_authority": False,
    }
    from investment_evidence_engine.contracts import ExecutionRequest

    sealed = ExecutionRequest.model_validate(request)
    sealed.request_sha256 = sealed.compute_hash()
    request_path = tmp_path / "request.json"
    request_path.write_text(sealed.model_dump_json(), encoding="utf-8")

    result = execute_request(
        request_path,
        output_dir=tmp_path / "output",
        executor_repo="riyuewuxing/InvestmentEvidenceEngine",
        executor_commit="b" * 40,
    )

    assert result.status == "BLOCK"
    assert result.operations[0].errors == ["MARKET_UNIVERSE_AS_OF_MISMATCH"]
    assert provider.primary_calls == 0


def test_quote_date_mismatch_is_not_marked_verified(tmp_path: Path) -> None:
    rows = _rows()
    rows["quote_trade_date"] = "2026-09-01"
    provider = FakeAKShare(primary=rows, listings=_listings())
    context = _context(tmp_path, provider)

    result = run_operation(_operation(min_universe_size=2), context)

    assert result.status == "WARN"
    assert context.payloads["universe"]["quote_trade_date_status"] == "MISMATCH"
    assert "MARKET_UNIVERSE_QUOTE_DATE_MISMATCH" in result.warnings


def test_scan_dependency_requires_completed_market_universe_provenance(tmp_path: Path) -> None:
    provider = FakeAKShare(primary=_rows(), listings=_listings())
    context = _context(tmp_path, provider)
    context.payloads["universe"] = {
        "source": "public_market_data",
        "public_data_only": True,
        "decision_authority": False,
        "as_of": AS_OF,
        "records": [{"code": "600519", "pct_change": 1.0}],
    }
    scan = ExecutionOperation(
        operation_id="scan",
        kind="OPPORTUNITY_SCAN",
        parameters={
            "as_of": AS_OF,
            "depends_on_operation_ids": ["universe"],
            "rules": [{"field": "pct_change", "operator": "GE", "threshold": 0}],
        },
    )

    result = run_operation(scan, context)

    assert result.status == "BLOCK"
    assert any(error.startswith("OPPORTUNITY_SCAN_DEPENDENCY") for error in result.errors)


def test_scan_dependency_does_not_trust_payload_kind_claim(tmp_path: Path) -> None:
    context = _context(tmp_path, FakeAKShare(primary=_rows(), listings=_listings()))
    context.completed_operations["universe"] = {
        "kind": "OPPORTUNITY_SCAN",
        "status": "PASS",
        "as_of": AS_OF,
    }
    context.payloads["universe"] = {
        "source": "public_market_data",
        "public_data_only": True,
        "decision_authority": False,
        "as_of": AS_OF,
        "records": [{"code": "600519", "pct_change": 1.0}],
    }
    scan = ExecutionOperation(
        operation_id="scan",
        kind="OPPORTUNITY_SCAN",
        parameters={
            "as_of": AS_OF,
            "depends_on_operation_ids": ["universe"],
            "rules": [{"field": "pct_change", "operator": "GE", "threshold": 0}],
        },
    )

    result = run_operation(scan, context)

    assert result.status == "BLOCK"
    assert "OPPORTUNITY_SCAN_DEPENDENCY_KIND_INVALID" in result.errors


def test_scan_dependency_requires_provenance_as_of_to_match(tmp_path: Path) -> None:
    context = _context(tmp_path, FakeAKShare(primary=_rows(), listings=_listings()))
    context.completed_operations["universe"] = {
        "kind": "MARKET_UNIVERSE",
        "status": "PASS",
        "as_of": "2026-09-01",
    }
    context.payloads["universe"] = {
        "source": "public_market_data",
        "public_data_only": True,
        "decision_authority": False,
        "as_of": AS_OF,
        "records": [{"code": "600519", "pct_change": 1.0}],
    }
    scan = ExecutionOperation(
        operation_id="scan",
        kind="OPPORTUNITY_SCAN",
        parameters={
            "as_of": AS_OF,
            "depends_on_operation_ids": ["universe"],
            "rules": [{"field": "pct_change", "operator": "GE", "threshold": 0}],
        },
    )

    result = run_operation(scan, context)

    assert result.status == "BLOCK"
    assert result.errors == ["OPPORTUNITY_SCAN_DEPENDENCY_AS_OF_INVALID"]


def test_live_scan_allows_missing_optional_numeric_values(tmp_path: Path) -> None:
    provider = FakeAKShare(primary=_rows(), listings=_listings())
    context = _context(tmp_path, provider)
    universe = run_operation(_operation(min_universe_size=2), context)
    assert universe.status == "PASS"
    scan = ExecutionOperation(
        operation_id="scan",
        kind="OPPORTUNITY_SCAN",
        parameters={
            "as_of": AS_OF,
            "depends_on_operation_ids": ["universe"],
            "rules": [{"field": "pe_dynamic", "operator": "LE", "threshold": 40}],
        },
    )

    result = run_operation(scan, context)

    assert result.status == "PASS"
    assert result.metrics["input_mode"] == "LIVE_MARKET_UNIVERSE"
    assert result.metrics["candidate_count"] == 2


def test_live_scan_blocks_when_rule_field_has_no_valid_numeric_values(tmp_path: Path) -> None:
    provider = FakeAKShare(primary=_rows(), listings=_listings())
    context = _context(tmp_path, provider)
    universe = run_operation(_operation(min_universe_size=2), context)
    assert universe.status == "PASS"
    context.payloads["universe"]["records"] = [
        {"code": "600519", "name": "贵州茅台", "pe_dynamic": None},
        {"code": "000001", "name": "平安银行", "pe_dynamic": None},
    ]
    scan = ExecutionOperation(
        operation_id="scan",
        kind="OPPORTUNITY_SCAN",
        parameters={
            "as_of": AS_OF,
            "depends_on_operation_ids": ["universe"],
            "rules": [{"field": "pe_dynamic", "operator": "LE", "threshold": 40}],
        },
    )

    result = run_operation(scan, context)

    assert result.status == "BLOCK"
    assert result.errors == ["OPPORTUNITY_SCAN_RULE_FIELD_NO_VALID_NUMERIC:pe_dynamic"]


def test_scan_dependency_rejects_inline_records_and_multiple_dependencies(tmp_path: Path) -> None:
    context = _context(tmp_path, FakeAKShare(primary=_rows(), listings=_listings()))
    scan = ExecutionOperation(
        operation_id="scan",
        kind="OPPORTUNITY_SCAN",
        parameters={
            "as_of": AS_OF,
            "depends_on_operation_ids": ["universe", "other"],
            "inline_records": [{"pct_change": 1.0}],
            "rules": [{"field": "pct_change", "operator": "GE", "threshold": 0}],
        },
    )

    result = run_operation(scan, context)

    assert result.status == "BLOCK"
    assert result.errors == ["OPPORTUNITY_SCAN_DEPENDENCY_INLINE_CONFLICT"]


def context_payload(tmp_path: Path) -> dict[str, object]:
    import json

    return json.loads((tmp_path / "universe.json").read_text(encoding="utf-8"))
