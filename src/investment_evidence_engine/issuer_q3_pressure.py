"""Same-version Q3 balance-sheet and cash-flow reconciliation, not advice."""
from __future__ import annotations

import re
from decimal import Decimal
from hashlib import sha256

from .issuer_revision_control import AMOUNT, normalize_text

EXPECTED_SHA = "dedeb15450b3005cb8f509cf1d3409347a76170ae5c7e9c5f21de04645ea3639"
# Values visually checked on issuer PDF pages 5–7, 9–10.
ROWS = {
    "cash": (5, "货币资金", "1,584,726,677.92", "1,822,362,695.32"),
    "current_assets": (6, "(?<!非)流动资产合计", "5,876,385,094.39", "6,433,195,628.56"),
    "construction": (6, "在建工程", "6,987,681,920.80", "4,068,071,345.03"),
    "noncurrent_assets": (6, "非流动资产合计", "28,949,228,632.11", "25,634,631,170.26"),
    "assets": (6, "资产总计", "34,825,613,726.50", "32,067,826,798.82"),
    "short_borrowing": (6, "短期借款", "2,302,673,290.42", "3,778,634,666.51"),
    "due_within_year": (7, "一年内到期的非流动负债", "1,815,864,096.34", "1,339,196,749.89"),
    "current_liabilities": (7, "(?<!非)流动负债合计", "8,458,397,377.04", "9,568,469,902.09"),
    "long_borrowing": (7, "长期借款", "8,072,081,881.94", "6,171,365,130.96"),
    "long_payable": (7, "长期应付款", "4,255,569,927.70", "2,355,840,713.97"),
    "noncurrent_liabilities": (7, "非流动负债合计", "15,290,171,623.50", "11,545,698,345.31"),
    "liabilities": (7, "(?<!流动)负债合计", "23,748,569,000.54", "21,114,168,247.40"),
    "parent_equity": (7, "归属于母公司所有者权益合计", "10,870,742,306.53", "10,758,535,847.11"),
    "minority_equity": (7, "少数股东权益", "206,302,419.43", "195,122,704.31"),
    "equity": (7, "(?<!归属于母公司)所有者权益合计", "11,077,044,725.96", "10,953,658,551.42"),
    "ocf": (10, "经营活动产生的现金流量净额", "504,959,757.35", "496,852,268.31"),
    "capex": (10, "购建固定资产、无形资产和其他长期资产支付的现金", "1,705,915,063.37", "1,059,747,940.14"),
    "investing": (10, "投资活动产生的现金流量净额", "-1,619,851,543.94", "-1,064,566,296.52"),
    "borrowing": (10, "取得借款收到的现金", "7,766,307,570.09", "6,616,231,974.90"),
    "repayment": (10, "偿还债务支付的现金", "5,562,481,080.43", "5,334,219,789.53"),
    "financing": (10, "筹资活动产生的现金流量净额", "1,317,978,390.67", "1,514,179,012.01"),
    "fx": (10, "汇率变动对现金及现金等价物的影响", "-4,861,205.73", "24,885,482.23"),
    "net_cash": (10, "现金及现金等价物净增加额", "198,225,398.35", "971,350,466.03"),
    "opening_cash_eq": (10, "期初现金及现金等价物余额", "782,255,256.65", "265,084,207.97"),
    "closing_cash_eq": (10, "期末现金及现金等价物余额", "980,480,655.00", "1,236,434,674.00"),
}


def extract_pressure(pages: dict[int, str]) -> dict:
    normalized = {i: normalize_text(s) for i, s in pages.items()}
    if set(normalized) != {5, 6, 7, 9, 10}:
        raise ValueError("Q3_PRESSURE_PAGE_SCOPE")
    if not all(s in normalized[5] for s in ("合并资产负债表", "2026年09月30日", "期初余额(已重述)")):
        raise ValueError("Q3_PRESSURE_BALANCE_SCOPE")
    if not all(s in normalized[9] for s in ("合并年初到报告期末现金流量表", "本期发生额", "上期发生额")):
        raise ValueError("Q3_PRESSURE_FLOW_SCOPE")
    values = {}
    for key, (page, label, a, b) in ROWS.items():
        matches = re.findall(label + "(" + AMOUNT + ")(" + AMOUNT + ")", normalized[page])
        if matches != [(a, b)]:
            raise ValueError("Q3_PRESSURE_ROW_MISMATCH")
        values[key] = tuple(Decimal(x.replace(",", "")) for x in matches[0])
    periods = []
    for i in (0, 1):
        v = {k: x[i] for k, x in values.items()}
        if not (v["current_assets"]+v["noncurrent_assets"] == v["assets"]
                and v["current_liabilities"]+v["noncurrent_liabilities"] == v["liabilities"]
                and v["parent_equity"]+v["minority_equity"] == v["equity"]
                and v["liabilities"]+v["equity"] == v["assets"]
                and v["ocf"]+v["investing"]+v["financing"]+v["fx"] == v["net_cash"]
                and v["opening_cash_eq"]+v["net_cash"] == v["closing_cash_eq"]):
            raise ValueError("Q3_PRESSURE_RECONCILIATION")
        periods.append({
            "balance_as_of": ("2026-09-30", "2026-01-01_RESTATED")[i],
            "flow_period": ("2026-01-01/2026-09-30", "2025-01-01/2025-09-30")[i],
            "rows_cny": {k: str(x) for k, x in v.items()},
            "current_ratio": str((v["current_assets"]/v["current_liabilities"]).quantize(Decimal(".0001"))),
            "liabilities_assets_pct": str((100*v["liabilities"]/v["assets"]).quantize(Decimal(".01"))),
            "ocf_cash_capex_proxy": str(v["ocf"]-v["capex"]),
            "ocf_capex_coverage_pct": str((100*v["ocf"]/v["capex"]).quantize(Decimal(".01"))),
            "net_borrowing_flow": str(v["borrowing"]-v["repayment"]),
        })
    return {"periods": periods, "reconciliation": "MATCH", "scope": "CONSOLIDATED_UNAUDITED",
            "page_sha256": {str(i): sha256(s.encode()).hexdigest() for i, s in normalized.items()},
            "cash_capex_proxy_not_fcff_fcfe": True, "full_debt_and_restricted_cash_unverified": True,
            "pit_safe": False, "decision_authority": False}
