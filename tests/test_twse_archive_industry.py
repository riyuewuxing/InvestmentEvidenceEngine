import csv
import io
import json
from datetime import timedelta

import pytest

from investment_evidence_engine.contracts import ExecutionOperation
from investment_evidence_engine.dispatch import run_operation
from investment_evidence_engine.twse_archive_industry import (
    DIGEST,
    PAIRS,
    PROFILE,
    VERIFIED,
    pair_summary,
    read_rows,
)
from investment_evidence_engine.twse_revenue_control import REQUIRED
from investment_evidence_engine.workers import WorkerContext


def op(**updates):
    params = {"industry_profile": PROFILE, "archive_sha256": DIGEST, "market": "TWSE",
              "subject_ids": ["TWSE:2330"], "as_of": VERIFIED.isoformat()}
    params.update(updates)
    return ExecutionOperation(operation_id="twse", kind="INDUSTRY_MACRO",
                              parameters=params, evidence_domains=["INDUSTRY_MACRO"])


def ctx(tmp_path, cutoff=VERIFIED):
    return WorkerContext(output_dir=tmp_path, request_as_of=cutoff.isoformat(),
                         clock=lambda: VERIFIED + timedelta(seconds=5))


def test_actual_archive_profile_via_dispatch(tmp_path):
    result = run_operation(op(), ctx(tmp_path))
    assert result.status == "WARN"
    payload = json.loads((tmp_path / "twse.json").read_text())
    assert payload["summary"]["observed_row_count"] == 1091
    assert payload["archive_rehash"] == "MATCH"
    assert payload["capture_visible_at_cutoff"] is True
    assert payload["pit_safe"] is False
    assert payload["decision_authority"] is False
    for group in payload["summary"]["groups"].values():
        for stats in group.values():
            assert stats["amount_paired_rows"] + stats["excluded_rows"] == stats["observed_rows"]


@pytest.mark.parametrize("updates", [
    {"as_of": (VERIFIED-timedelta(microseconds=1)).isoformat()},
    {"as_of": "2026-11-26"},
    {"as_of": (VERIFIED+timedelta(seconds=6)).isoformat()},
    {"archive_sha256": "0" * 64},
    {"market": "CN_A"},
    {"subject_ids": ["2330"]},
    {"industry_profile": "unknown"},
    {"inline_records": []},
])
def test_fail_closed_before_verification_or_wrong_scope(tmp_path, updates):
    result = run_operation(op(**updates), ctx(tmp_path))
    assert result.status == "BLOCK"
    assert not (tmp_path / "twse.json").exists()


def test_sealed_request_ceiling_cannot_be_extended(tmp_path):
    result = run_operation(op(), ctx(tmp_path, VERIFIED-timedelta(seconds=1)))
    assert result.status == "BLOCK"


def test_amount_pairs_and_rate_conflicts_not_silently_filled():
    a, b, c = PAIRS["yoy"]
    rows = [{"公司代號": "2330", a: "120", b: "100", c: "20"},
            {"公司代號": "2303", a: "0", b: "100", c: "-100"},
            {"公司代號": "2329", a: "99", b: "0", c: "-"},
            {"公司代號": "2302", a: "-1", b: "100", c: "-101"},
            {"公司代號": "2301", a: "", b: "10", c: "0"},
            {"公司代號": "2304", a: "150", b: "100", c: "1"}]
    r = pair_summary(rows, PAIRS["yoy"])
    assert r["amount_paired_rows"] == 3 and r["excluded_rows"] == 3
    assert r["positive_rows"] == 2 and r["negative_rows"] == 1
    assert r["aggregate_paired_growth_pct"] == "-10.000000"
    assert r["provider_rate_checks"] == {"MATCH": 2, "CONFLICT": 1, "MISSING_OR_UNPARSEABLE": 0}
    assert r["exclusion_reasons"] == {"MISSING_OR_INVALID_AMOUNT": 1, "NEGATIVE_AMOUNT": 1,
                                     "ZERO_COMPARISON_BASE": 1}


def test_duplicate_and_mixed_snapshot_block():
    row = dict.fromkeys(REQUIRED, "0")
    row.update({"公司代號": "2330", "公司名稱": "台積電", "產業別": "半導體業",
                "資料年月": "11510", "出表日期": "1151117"})
    def body(rows):
        out = io.StringIO()
        w = csv.DictWriter(out, fieldnames=sorted(REQUIRED))
        w.writeheader()
        w.writerows(rows)
        return out.getvalue().encode()
    with pytest.raises(ValueError, match="IDENTITY_SCOPE"):
        read_rows(body([row, row]))
    with pytest.raises(ValueError, match="MIXED_PERIOD"):
        read_rows(body([row | {"資料年月": "11509"}]))
