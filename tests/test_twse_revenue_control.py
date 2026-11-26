import csv
import io
from datetime import UTC, datetime

import pytest

from investment_evidence_engine.twse_revenue_control import (
    AMOUNTS,
    PERCENTS,
    REQUIRED,
    compare,
    compare_issuer_table,
    parse_exchange,
    parse_issuer_table,
)

NOW = datetime(2026, 11, 26, 13, tzinfo=UTC)


def body(**overrides):
    row = {"出表日期": "1151126", "資料年月": "11510", "公司代號": "2330",
           "公司名稱": "台積電", "產業別": "半導體業", "備註": ""}
    row.update(zip(AMOUNTS, ("586890000", "511857000", "367473000", "4485617000", "3130437000"), strict=True))
    row.update(zip(PERCENTS, ("14.66", "59.71", "43.29"), strict=True))
    row.update(overrides)
    file = io.StringIO()
    writer = csv.DictWriter(file, fieldnames=sorted(REQUIRED))
    writer.writeheader()
    writer.writerow(row)
    return file.getvalue().encode("utf-8-sig")


def issuer():
    return {"symbol": "2330", "period": "2026-10-01", "unit": "TWD_MILLIONS",
            "amounts": [586890, 511857, 367473, 4485617, 3130437],
            "reported_rates_pct": ["14.7", "59.7", "43.3"]}


def test_exact_reported_period_and_units():
    row = parse_exchange(body(), NOW)
    assert row["snapshot_date"] == "2026-11-26"
    assert row["amounts"][0] == 586890000
    result = compare(row, issuer())
    assert result["comparison"] == "MATCH_WITH_DECLARED_ROUNDING"
    assert not result["pit_safe"]
    assert not result["cross_market_causal_link_verified"]


@pytest.mark.parametrize("overrides, error", [
    ({"資料年月": "11509"}, "PERIOD"),
    ({"出表日期": "1151127"}, "SNAPSHOT"),
    ({"出表日期": "1151101"}, "SNAPSHOT"),
    ({"公司代號": "2303"}, "TARGET_MISSING"),
    ({"營業收入-當月營收": ""}, "AMOUNT"),
    ({"營業收入-上月比較增減(%)": "0"}, "RATE_RECONCILIATION"),
])
def test_wrong_scope_never_becomes_current_evidence(overrides, error):
    with pytest.raises(ValueError, match=error):
        parse_exchange(body(**overrides), NOW)


def test_mismatch_cannot_be_rescaled_until_it_passes():
    row = parse_exchange(body(), NOW)
    pdf = issuer()
    pdf["amounts"][0] += 1
    assert compare(row, pdf)["status"] == "BLOCK"
    pdf = issuer()
    pdf["unit"] = "TWD"
    with pytest.raises(ValueError, match="COMPARISON_SCOPE"):
        compare(row, pdf)


def test_current_issuer_table_matches_limited_subset_not_original_pdf():
    html = ("<h1>2026 Monthly Revenue</h1> In Millions of New Taiwan Dollars "
            "<table><tr><td>Sept.</td><td>511,857</td><td>54.6%</td></tr>"
            "<tr><td>Oct.</td><td>586,890</td><td>59.7%</td></tr>"
            "<tr><td>Total</td><td>4,485,617</td><td>43.3%</td></tr></table>"
            "Year 2026 figures have not been audited.")
    table = parse_issuer_table(html.encode())
    result = compare_issuer_table(parse_exchange(body(), NOW), table)
    assert result["comparison"] == "MATCH_CURRENT_TABLE_SUBSET"
    assert not result["original_issuer_pdf_runner_verified"]
    assert not result["pit_safe"]
    with pytest.raises(ValueError, match="TSMC_TABLE_ROWS_MISSING"):
        parse_issuer_table(html.replace("Oct.", "Nov.").encode())

def test_observed_exchange_rate_precision_regression():
    # Bounded numeric fields from public run 45832825328, not a retained raw CSV.
    observed_amounts = ("586890319", "511857399", "367473051", "4485617293", "3130436902")
    observed_rates = ("14.658949962741477", "59.709757600700904", "43.29045540365918")
    row = parse_exchange(body(**dict(zip(AMOUNTS + PERCENTS, observed_amounts + observed_rates, strict=True))), NOW)
    assert row["reported_rates_pct"] == list(observed_rates)
    assert compare(row, issuer())["comparison"] == "MATCH_WITH_DECLARED_ROUNDING"
    assert not row["historical_vintage_verified"]
    with pytest.raises(ValueError, match="PERCENT_SCHEMA"):
        parse_exchange(body(**{PERCENTS[0]: "14." + "1" * 19}), NOW)
