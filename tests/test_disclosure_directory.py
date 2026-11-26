import json

import pytest

from investment_evidence_engine.disclosure_directory import parse_directory


def rows():
    return [{"code": f"{prefix}{i:03d}", "orgId": f"org-{prefix}-{i}", "category": "A股"}
            for prefix in ("000", "600") for i in range(1000)]


def encoded(data):
    return json.dumps({"stockList": data}, ensure_ascii=False).encode()


def test_prefix_coverage_is_not_listing_or_pit():
    data = rows() + [{"code": "900001"}]
    codes, meta = parse_directory(encoded(data))
    assert len(codes) == 2000 and meta["out_of_scope"] == 1
    assert meta["code_stats"]["sh_count"] == meta["code_stats"]["sz_count"] == 1000
    assert not meta["active_listing_verified"] and not meta["listing_completeness_verified"]
    assert not meta["pit_safe"] and not meta["decision_authority"]


@pytest.mark.parametrize("fault", ["duplicate", "bad_code", "missing_org", "missing_category", "thin"])
def test_directory_fails_closed_on_ambiguous_input(fault):
    data = rows()
    if fault == "duplicate":
        data.append(data[0])
    elif fault == "bad_code":
        data[0]["code"] = 1
    elif fault == "missing_org":
        data[0]["orgId"] = ""
    elif fault == "missing_category":
        del data[0]["category"]
    else:
        data.pop()
    with pytest.raises(ValueError):
        parse_directory(encoded(data))
