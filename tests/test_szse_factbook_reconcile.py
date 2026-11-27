from investment_evidence_engine.szse_factbook_reconcile import (
    capco_codes,
    compare_sets,
    row_anomalies,
)


def test_classification_code_rows_require_company_name():
    assert capco_codes("000035 中国天楹 N 77 生态保护\n000001 平安银行 J 66 货币金融", sorted_by_code=True)==(
        ["000035","000001"],0)
    assert capco_codes("农林牧渔(A) 01 农业 002772 众兴菌业", sorted_by_code=False)==(["002772"],0)
    assert capco_codes("000035 000036 中国天楹\n000001", sorted_by_code=True)==([],2)


def test_duplicate_and_inversion_not_hidden():
    rows=[(1,"000035","000035","1.00","1.00"),(2,"000035","000035","2.00","1.00")]
    r=row_anomalies(rows,"main")
    assert r["duplicate_counts"]=={"market":1,"negotiable":1}
    assert r["inversion_counts"]=={"market":1,"negotiable":0}
    assert r["unique_market_codes"]==1
    assert not r["market_value_sum_within_rounding_bound"]


def test_set_differences_not_listing_events():
    r=compare_sets({"000035","600190"},{"000035","600519"})
    assert r["intersection"]==1 and r["left_only"]==r["right_only"]==1
    assert r["membership_changes_are_not_verified_listings_or_delistings"]
