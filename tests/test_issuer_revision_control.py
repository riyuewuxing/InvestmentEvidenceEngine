import pytest

from investment_evidence_engine.issuer_revision_control import (
    DOCS,
    EXPECTED,
    LABELS,
    ROOT,
    extract_checked_rows,
    revision_diagnostic,
)


def table(kind):
    return " ".join(f"{LABELS[key]}（元）{values[0]} {values[1]} {values[2]}"
                    for key, values in EXPECTED[kind].items())


@pytest.mark.parametrize("kind", list(EXPECTED))
def test_exact_page_row_order(kind):
    rows = extract_checked_rows(kind, table(kind))
    assert rows["assets"][0] == EXPECTED[kind]["assets"][0].replace(",", "")


def test_annual_percentage_column():
    text = table("annual_2025").replace("29,320,007,895.30 ", "29,320,007,895.30 9.43% ")
    assert extract_checked_rows("annual_2025", text)["assets"][1] == "29320007895.30"


def test_row_mismatch_does_not_fill_missing_data():
    with pytest.raises(ValueError, match="ROW_OR_ORDER_MISMATCH"):
        extract_checked_rows("half_2026", table("half_2026").replace("32,067,826,798.82", "32,067,826,798.83"))


def receipts():
    rows = []
    for kind, (suffix, _, _) in DOCS.items():
        item = {"kind": kind, "url": ROOT+suffix, "status": "OBSERVED",
                "declared_document_date": suffix.split("/")[0],
                "retrieved_at": "2026-11-26T12:00:00+00:00"}
        if kind == "policy_2026":
            item["retrospective_adjustment_declared"] = True
        else:
            item["table_rows_cny"] = extract_checked_rows(kind, table(kind))
        rows.append(item)
    return rows


def test_revision_is_real_version_difference_not_historical_availability():
    result = revision_diagnostic(receipts())
    assert result["comparison"][0]["adjustment_cny"] == "-16514584.36"
    assert result["comparison"][1]["adjustment_cny"] == "-134432992.12"
    assert not result["pit_safe"] and not result["decision_authority"]
    assert "half_2026" not in result["cutoff_checks"][1]["document_date_screen_only"]
    assert all(not row["actually_observed_by_cutoff"] for row in result["cutoff_checks"])


def test_cross_document_original_link_required():
    data = receipts()
    data[-1]["table_rows_cny"]["assets"] = ("1", "2", "3")
    with pytest.raises(ValueError, match="COMPARATIVE_LINK_MISMATCH"):
        revision_diagnostic(data)
