from decimal import Decimal

import pytest

from investment_evidence_engine.dividend_accounting_control import _row, reconcile


def test_row_is_anchored_and_column_order_checked():
    label = "3.对所有者(或股东)的分配"
    expected = ("-84,058,749.07", "-84,058,749.07", "-20,419,710.44", "-104,478,459.51")
    raw = label + "".join(expected)
    assert _row(raw, label, expected)[0] == "-84058749.07"
    for invalid in (raw+raw, raw.replace("20,419,710.44", "20,419,710.45"),
                    raw.replace(label, "其他"), label+"".join(reversed(expected))):
        with pytest.raises(ValueError):
            _row(invalid, label, expected)


def receipts():
    data = []
    for name, parent, minority, total in (
        ("half_2025", "84058749.04", "16745050.47", "100803799.51"),
        ("annual_2025", "84058749.07", "20419710.44", "104478459.51"),
        ("half_2026", "85969179.68", "12600000.00", "98569179.68"),
    ):
        data.append({"kind": name, "status": "OBSERVED", "fields": {
            "parent_distribution_cny": parent, "minority_distribution_cny": minority,
            "total_consolidated_distribution_cny": total,
            "comparative_2025_h1_parent_distribution_cny": "84058749.04"}})
    data += [{"kind": f"approval_{y}", "status": "OBSERVED", "fields": {"approved": True}}
             for y in (2025, 2026)]
    return data


def test_accounting_differences_are_not_forced_to_equal_or_payment():
    out = reconcile(receipts(), {"2025": "84058753.47", "2026": "85969179.68"})
    assert Decimal(out["2025_implementation_minus_annual_accounting_cny"]) == Decimal("4.40")
    assert Decimal(out["2025_implementation_minus_h1_accounting_cny"]) == Decimal("4.43")
    assert Decimal(out["2025_annual_minus_h1_cny"]) == Decimal(".03")
    assert Decimal(out["2026_implementation_minus_h1_accounting_cny"]) == 0
    assert not out["event_specific_cash_paid_verified"]
    assert not out["amount_difference_cause_verified"]


@pytest.mark.parametrize("fault", ["missing", "blocked", "wrong_total", "wrong_comparative"])
def test_missing_or_inconsistent_sources_block(fault):
    data = receipts()
    if fault == "missing":
        data.pop()
    elif fault == "blocked":
        data[0]["status"] = "BLOCK"
    elif fault == "wrong_total":
        data[0]["fields"]["total_consolidated_distribution_cny"] = "100803799.50"
    else:
        data[2]["fields"]["comparative_2025_h1_parent_distribution_cny"] = "84058749.07"
    with pytest.raises(ValueError):
        reconcile(data, {"2025": "84058753.47", "2026": "85969179.68"})
