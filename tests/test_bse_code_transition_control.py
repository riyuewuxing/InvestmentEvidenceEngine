import pytest

from investment_evidence_engine.bse_code_transition_control import (
    PILOTS,
    mapping_fields,
    notice_fields,
    parse_page,
)


def table(*, wrong=False, missing=False):
    # Synthetic rows; only the six public pilot and one suffix counterexample
    # are fixed evidence examples. A fixture is not a live listing.
    pairs = [(name, old, new) for old, (new, name) in PILOTS.items()]
    pairs += [("芭薇股份", "837023", "920123")]
    reserved = {new for _, _, new in pairs}
    remaining = [i for i in range(1, 1000) if f"920{i:03d}" not in reserved][:241]
    pairs += [(f"fixture{i}", f"840{i:03d}", f"920{i:03d}") for i in remaining]
    if wrong:
        pairs[-1] = pairs[-1][0], pairs[-2][1], pairs[-1][2]
    if missing:
        pairs.pop()
    html = ("新旧代码对照表<table><tr><th>序号</th><th>证券简称</th>"
            "<th>上市日期</th><th>旧代码</th><th>新代码</th></tr>")
    for i, (name, old, new) in enumerate(pairs, 1):
        html += (f"<tr><td>{i}</td><td>{name}</td><td>2020/7/27</td>"
                 f"<td>{old}</td><td>{new}</td></tr>")
    return parse_page((html + "</table>原精选层的挂牌日期").encode(), "utf-8")


def test_mapping_is_not_active_universe():
    fields = mapping_fields(table())
    assert fields["mapped_legacy_security_count"] == 248
    assert fields["pilot_count"] == 6
    assert fields["other_mapped_count"] == 242
    assert fields["suffix_counterexample"] == {"old": "837023", "new": "920123"}
    assert fields["selected_layer_date_before_bse_open_count"] == 248
    assert not fields["active_listing_verified"]


@pytest.mark.parametrize("kwargs", [{"wrong": True}, {"missing": True}])
def test_mapping_rejects_duplicate_or_partial_table(kwargs):
    with pytest.raises(ValueError, match="BSE_MAPPING_COUNT_OR_DUPLICATE"):
        mapping_fields(table(**kwargs))


@pytest.mark.parametrize("kind, body, effective", [
    ("pilot_effective", "2025年4月25日 存量上市公司代码切换试点上线 自2025年5月6日起 "
     "其他242只存量上市公司股票", "2025-05-06"),
    ("bulk_effective", "2025年9月12日 存量上市公司代码切换上线 自2025年10月9日起 "
     "存量股票启用新证券代码", "2025-10-09"),
])
def test_declared_dates_not_actual_historical_capture(kind, body, effective):
    fields = notice_fields(kind, parse_page(body.encode(), "utf-8"))
    assert fields["declared_effective_day"] == effective
    assert not fields["historical_first_availability_verified"]
    with pytest.raises(ValueError, match="BSE_NOTICE_FIELDS"):
        notice_fields(kind, parse_page(body.replace("起", "后").encode(), "utf-8"))


def test_pilot_name_list_requires_all_six():
    body = "2025年4月11日 存量上市公司代码切换试点股票名单 6只股票进行试点切换 "
    body += "、".join(name for _, name in PILOTS.values())
    assert notice_fields("pilot_names", parse_page(body.encode(), "utf-8"))["declared_effective_day"] is None
    with pytest.raises(ValueError, match="BSE_NOTICE_FIELDS"):
        notice_fields("pilot_names", parse_page(body.replace("龙竹科技", "").encode(), "utf-8"))
