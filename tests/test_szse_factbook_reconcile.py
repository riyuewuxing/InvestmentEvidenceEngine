from investment_evidence_engine.szse_factbook_reconcile import (
    aidier_fields,
    capco_codes,
    compare_sets,
    counts_from_text,
    overview_fields,
    partition_reconciled,
    row_anomalies,
    tail_partition,
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


def test_counts_and_tail_remain_diagnostic_only():
    text = ("国内证券市场数据(2024年12月底)\nA股(只) 2 1 1 2 1 1 1 5\n"
            "B股(只) 1 1 0 1 1 0 0 2\n合计(只) 3 2 1 3 2 1 1 7\n"
            "上市公司数(家) 2 1 1 2 1 1 1 5")
    counts = counts_from_text(text)
    assert counts["counts"]["a"][7]==5
    assert not counts["member_identities_verified"]
    rows=[(1,"000001","201872","3","3"),(2,"201872","000001","2","2"),
          (3,"002776","002776","1","1")]
    result=tail_partition(rows,2,"201872")
    assert result["first_left_class_counts"]=={"a":1,"b":1,"unknown":0}
    assert result["tail_only_left"]==["002776"]
    assert not result["historical_member_admission"]


def test_partition_checks_reject_count_match_but_invalid_rank_or_value():
    p={"first_rows":1521,"first_unique_left":1521,"first_unique_right":1521,
       "first_sets_match":True,"first_descending":True,"first_rank_sequence_match":True,
       "first_market_value_delta_million":"0.01"}
    assert partition_reconciled(p,1521)
    for field in ("first_sets_match","first_descending","first_rank_sequence_match"):
        assert not partition_reconciled(p | {field:False},1521)
    assert not partition_reconciled(p | {"first_market_value_delta_million":"8"},1521)


def test_aidier_decision_and_exit_are_distinct():
    common="福建省爱迪尔珠宝实业股份有限公司 002740 人民币普通股 2024年2月8日 深证上〔2024〕126号 "
    d=aidier_fields(common+"2024-019 关于收到股票终止上市决定的公告","aidier_decision")
    assert d["issuer_reported_delisting_day"] is None
    e=aidier_fields(common+"2024-023 关于股票终止上市暨摘牌的公告 摘牌日期：2024年3月4日","aidier_exit")
    assert e["issuer_reported_delisting_day"]=="2024-03-04"
    assert not e["first_availability_verified"]


def test_overview_uses_company_counts_and_rounded_aggregate_not_membership():
    pages=[f"2024 年{title}市场概况\n截至 2024. 12. 31\n上市公司数 {n} 0 0\n总市值（亿元） {v} 0 0"
           for title,n,v in [("深圳证券",2852,"330411.53"),("主板",1487,"205870.81"),("创业板",1365,"124540.72")]]
    got=overview_fields(pages)
    assert got["company_count_differences"]==[1,1,0]
    assert not got["company_count_difference_cause_verified"]
    assert not got["member_identities_verified"]
