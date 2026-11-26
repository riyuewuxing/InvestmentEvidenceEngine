from datetime import date

import pytest

from investment_evidence_engine.sse_lifecycle_control import parse_notice, scheduled_state


def test_delisting_period_end_not_removal():
    html = """<h1>关于湖北九有投资股份有限公司股票摘牌的公告</h1>
    <p>2025-07-14</p><p>湖北九有投资股份有限公司发行的股票（证券简称为“退市九有”，证券代码为“600462”）
    已被本所决定终止上市，退市整理期于2025年7月14日届满，本所于2025年7月21日对其予以摘牌。</p>
    <p>上海证券交易所</p>"""
    f = parse_notice(html.encode(), "exit")
    assert scheduled_state(f, date(2025, 7, 14)) == "BEFORE_ANNOUNCED_TERMINATION_TRADABILITY_UNKNOWN"
    assert scheduled_state(f, date(2025, 7, 15)) == "AFTER_DELISTING_PERIOD_BEFORE_REMOVAL"
    assert scheduled_state(f, date(2025, 7, 21)) == "ANNOUNCED_TERMINATION_DATE_REACHED"
    assert not f["historical_capture_verified"]
    assert not f["tradability_verified"]
    with pytest.raises(ValueError, match="EVENT_SCOPE"):
        parse_notice(html.replace("600462", "600463").encode(), "exit")
    with pytest.raises(ValueError, match="EVENT_SCOPE"):
        parse_notice(html.replace("<p>湖北", "<script>湖北").replace("摘牌。</p>", "摘牌。</script>").encode(), "exit")


def test_ipo_not_listed_before_effective():
    html = """<h1>关于超颖电子电路股份有限公司人民币普通股股票上市交易的公告</h1><p>2025-10-23</p>
    <p>超颖电子电路股份有限公司A股股票将在本所上市交易。该公司A股股本为43702.9321万股，
    其中4399.9308万股于2025年10月24日起上市交易。证券简称为"超颖电子",证券代码为"603175"。</p>
    <p>上海证券交易所</p>"""
    f = parse_notice(html.encode(), "ipo")
    assert scheduled_state(f, date(2025, 10, 23)) == "PRE_ANNOUNCED_LISTING"
    assert scheduled_state(f, date(2025, 10, 24)) == "ANNOUNCED_LISTING_DATE_REACHED"
    with pytest.raises(ValueError, match="EVENT_SCOPE"):
        parse_notice(html.replace("10月24日", "10月25日").encode(), "ipo")
