import json
from datetime import date
from hashlib import sha256

import pytest
from test_input_binding import fixture

from investment_evidence_engine.market_calendar import scheduled_days
from investment_evidence_engine.research_profile_evidence import (
    COST,
    FACTOR,
    PROFILE,
    SPLIT,
    check_profile,
    evaluate_market_profile,
)
from investment_evidence_engine.runner import execute_request


def params(ref):
    return {"as_of": ref.as_of, "input_artifact_ids": [ref.input_id],
            "depends_on_operation_ids": ["market"], "profile": PROFILE,
            "factor": FACTOR, "split": SPLIT, "cost": COST,
            "semantics": "RESEARCH_ONLY_NOT_ADVICE", "market": "CN_A", "asset_type": "STOCK"}


def payload(symbol="600519", as_of="2026-11-25"):
    first, last = date(2025, 1, 2), date(2026, 11, 24)
    bars = [{"date": row.day.isoformat() + "T00:00:00.000", "open": 100+i/10,
             "high": 102+i/10, "low": 99+i/10, "close": 101+i/10, "volume": 1000}
            for i, row in enumerate(scheduled_days(first, last)) if row.is_trading_day]
    return {"symbol": symbol, "as_of": as_of, "start": first.isoformat(), "end": last.isoformat(),
            "adjust": "", "history_end_offset_days": 1, "pit_safe": False,
            "historical_vintage_verified": False, "decision_authority": False,
            "bars": bars, "crosscheck": {"status": "MATCH_OBSERVED_ROWS", "overlap_rows": len(bars),
                "left_only_dates": 0, "right_only_dates": 0, "latest_common_date": last.isoformat(),
                "tolerance": 0.001, "max_relative_price_diff": 0.0},
            "providers": [{"upstream": "sina", "status": "OBSERVED", "rows": len(bars)},
                          {"upstream": "tencent", "status": "OBSERVED", "rows": len(bars),
                           "raw_body_parent_rehash": "MATCH"}]}


def test_profile_reuses_fixed_momentum_only_on_raw_scope():
    p = payload()
    raw = json.dumps(p).encode()
    report = evaluate_market_profile(raw, symbol=p["symbol"], as_of=p["as_of"])
    assert report["input_market_sha256"] == sha256(raw).hexdigest()
    assert not report["formal_profile_admitted"] and not report["pit_safe"]
    assert len(report["raw_price_diagnostic"]["segments"]) == 3


@pytest.mark.parametrize("change", ["adjust", "scope", "missing", "reverse", "duplicate", "boolean",
                                    "identity", "overlap", "provider", "pit"])
def test_invalid_profile_input_fails_closed(change):
    p = payload()
    if change == "adjust":
        p["adjust"] = "qfq"
    elif change == "scope":
        p["as_of"] = "2026-11-26"
    elif change == "missing":
        p["bars"].pop(10)
    elif change == "reverse":
        p["bars"].reverse()
    elif change == "duplicate":
        p["bars"][10] = p["bars"][11]
    elif change == "boolean":
        p["bars"][10]["volume"] = True
    elif change == "identity":
        p["bars"][10]["symbol"] = "000001"
    elif change == "overlap":
        p["crosscheck"]["left_only_dates"] = 1
    elif change == "provider":
        p["providers"][1]["raw_body_parent_rehash"] = "UNVERIFIED"
    else:
        p["pit_safe"] = True
    with pytest.raises(ValueError):
        evaluate_market_profile(json.dumps(p).encode(), symbol="600519", as_of="2026-11-25")


@pytest.mark.parametrize("key,value", [("cost", {**COST, "base_bps": 0}),
                                      ("factor", {**FACTOR, "window": 10}),
                                      ("split", {**SPLIT, "purge": True}),
                                      ("extra", True)])
def test_profile_contract_no_tuning(tmp_path, key, value):
    _, _, ref = fixture(tmp_path)
    with pytest.raises(ValueError):
        check_profile(params(ref) | {key: value})


@pytest.mark.parametrize("tamper", [False, True])
def test_sealed_chain_retains_diagnostic_but_formal_admission_blocks(tmp_path, monkeypatch, tamper):
    import pandas as pd

    from investment_evidence_engine.contracts import ArtifactRef, ExecutionRequest, OperationResult
    from investment_evidence_engine.dispatch import EXTRA_WORKERS

    reqfile, _, ref = fixture(tmp_path)
    request = ExecutionRequest.model_validate_json(reqfile.read_bytes())
    request.operations[1].parameters = params(ref)
    request.request_sha256 = request.compute_hash()
    reqfile.write_text(request.model_dump_json(), encoding="utf-8")

    def market(op, context):
        p = payload()
        raw = json.dumps(p).encode()
        path = context.output_dir / "market.json"
        path.write_bytes(raw)
        context.frames["market"] = pd.DataFrame(p["bars"])
        context.payloads["market"] = p
        if tamper:
            context.payloads["market"] = p | {"symbol": "600519", "extra": True}
        return OperationResult(operation_id="market", status="WARN",
                               artifacts=[ArtifactRef(path="market.json", sha256=sha256(raw).hexdigest(),
                                                      size_bytes=len(raw))])

    monkeypatch.setitem(EXTRA_WORKERS, "MARKET_DATA", market)
    out = tmp_path / "out"
    result = execute_request(reqfile, output_dir=out, executor_repo="public/example",
                             executor_commit="e"*40, input_root=tmp_path)
    assert result.status == "BLOCK"
    op = result.operations[1]
    readiness = op.metrics["research_readiness"]
    assert readiness["formal_profile"] == "NOT_ADMITTED"
    if tamper:
        assert readiness["arithmetic_profile"] == "BLOCK"
        assert not op.artifacts
    else:
        assert readiness["arithmetic_profile"] == "EXECUTED_RETROSPECTIVE_ONLY"
        assert len(op.artifacts) == 1
        raw = (out / "research.json").read_bytes()
        assert sha256(raw).hexdigest() == op.artifacts[0].sha256
        report = json.loads(raw)
        assert report["candidate_attachment_sha256"] == ref.source_artifact_sha256
        assert report["status"] == "BLOCK" and report["decision_authority"] is False
        assert "features" not in report and "pit" not in report


def test_portable_math_matches_existing_retrospective_wrapper():
    import pandas as pd

    from investment_evidence_engine.retrospective_control import retrospective_momentum

    p = payload()
    old = retrospective_momentum(pd.DataFrame(p["bars"]), date.fromisoformat(p["start"]),
                                 date.fromisoformat(p["end"]))
    report = evaluate_market_profile(json.dumps(p).encode(), symbol=p["symbol"], as_of=p["as_of"])
    assert report["raw_price_diagnostic"] == old


@pytest.mark.parametrize("field,value", [("open", 0), ("low", -1), ("high", 1), ("volume", 0)])
def test_portable_math_rejects_invalid_ohlcv(field, value):
    p = payload()
    p["bars"][10][field] = value
    with pytest.raises(ValueError, match="RESEARCH_MARKET_ROW_OHLCV"):
        evaluate_market_profile(json.dumps(p).encode(), symbol=p["symbol"], as_of=p["as_of"])
