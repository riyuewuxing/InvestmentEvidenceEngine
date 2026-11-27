from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest

from investment_evidence_engine.index_snapshot_scope import (
    COUNT,
    IN,
    OUT,
    digest_codes,
    expected_exchange,
    git_blob_sha1,
    membership_difference,
    parse_csv,
    parse_notice,
    parse_rows,
    snapshot_summary,
)


def fixture(weighted=False):
    h = ["日期Date", "指数代码Index Code", "指数名称Index Name", "指数英文名称Index Name(Eng)",
         "成份券代码Constituent Code", "成份券名称Constituent Name",
         "成份券英文名称Constituent Name(Eng)", "交易所Exchange", "交易所英文名称Exchange(Eng)"]
    if weighted:
        h.append("权重(%)Weight(%)")
    rows = [h]
    for n in range(COUNT):
        row = [20260506, 300, "沪深300", "CSI 300", n+1, "合成", "synthetic", "深圳", "Shenzhen"]
        rows.append(row + ([0.333] if weighted else []))
    return rows


def test_snapshot_scope_and_unrounded_weights():
    s = parse_rows(fixture(True), weighted=True, latest_label=date(2026, 5, 6))
    out = snapshot_summary(s)
    assert out["members"] == 300
    assert out["source_label_day"] == "2026-05-06"
    assert Decimal(out["reported_weight_sum_pct"]) == Decimal("99.900")
    assert Decimal(out["top10_reported_weight_pct"]) == Decimal("3.330")
    assert out["effective_member_count_from_reported_weights"] == "300.00"
    assert not out["historical_availability_verified"]
    assert not out["decision_authority"]


@pytest.mark.parametrize("row,col,value", [
    (1, 0, 20260507), (1, 0, 20260505), (1, 1, "000905"),
    (1, 2, "中证500"), (1, 4, 2), (1, 4, "001.0"), (1, 7, "上海"),
    (1, 5, ""), (0, 4, "unknown"), (0, 5, "成份券代码Constituent Code"),
])
def test_bad_scope_blocked(row, col, value):
    f = fixture()
    f[row][col] = value
    with pytest.raises(ValueError):
        parse_rows(f, weighted=False, latest_label=date(2026, 5, 6))


@pytest.mark.parametrize("value", [0, -0.1, "NaN", 100, True, "1e-3"])
def test_bad_weight_blocked(value):
    f = fixture(True)
    f[1][-1] = value
    with pytest.raises(ValueError):
        parse_rows(f, weighted=True, latest_label=date(2026, 5, 6))


def test_csv_and_blob_exact_scope():
    s = parse_rows(fixture(), weighted=False, latest_label=date(2026, 5, 6))
    raw = ("code\r\n" + "\r\n".join(s["codes"]) + "\r\n").encode()
    assert parse_csv(raw) == s["codes"]
    assert git_blob_sha1(b"test\n") == "9daeafb9864cf43055ae93beb0afd6c7d144bfa4"
    assert digest_codes(s["codes"]) == digest_codes(list(reversed(s["codes"])))
    with pytest.raises(ValueError):
        parse_csv(raw.replace(b"000002", b"000001"))


def test_notice_and_snapshot_delta_exact():
    page = ("沪深300指数样本调整名单：调出名单 调入名单 证券代码 证券名称 "
            + " ".join(f"{a}甲{b}乙" for a, b in zip(OUT, IN, strict=True))
            + " 中证500指数样本调整名单：")
    notice = parse_notice(page)
    # Synthetic base membership, not a historical original roster.
    common = [f"{n:06d}" for n in range(1, 282)]
    before = {"index_code": "000300", "label_day": "2026-05-06", "codes": common+list(OUT)}
    after = {"index_code": "000300", "label_day": "2026-06-16", "codes": common+list(IN)}
    d = membership_difference(before, after, notice=notice)
    assert d["reviewed_notice_set_match"] and d["common_members"] == 281
    assert not d["complete_intermediate_event_stream_verified"]
    with pytest.raises(ValueError):
        parse_notice(page.replace(OUT[0], "000999", 1))
    changed = deepcopy(after)
    changed["codes"][-1] = "688522"
    assert not membership_difference(before, changed, notice=notice)["reviewed_notice_set_match"]
    with pytest.raises(ValueError):
        membership_difference(after, before)


def test_reviewed_exceptional_szse_identity_not_prefix():
    assert expected_exchange("302132") == "SZ"
    with pytest.raises(ValueError):
        expected_exchange("302133")
    rows = fixture()
    rows[1][4:6] = [302132, "中航成飞"]
    assert parse_rows(rows, weighted=False, latest_label=date(2026, 5, 6))["names"]["302132"] == "中航成飞"
    rows[1][7] = "上海"
    with pytest.raises(ValueError):
        parse_rows(rows, weighted=False, latest_label=date(2026, 5, 6))
