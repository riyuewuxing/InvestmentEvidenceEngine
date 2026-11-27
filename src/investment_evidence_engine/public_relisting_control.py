"""Fixed public relisting counterexample: issuer continuity is not listing continuity.

Official notice assertions and bounded vendor observations only. No inferred
historical availability, OTC price history, ownership conversion or fills.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.request import Request, build_opener

from .bounded_worker import run_json_worker, write_worker_result
from .historical_capture import PublicSecurity, _provider_rows
from .issuer_disclosure_index import NoRedirect
from .sse_lifecycle_control import VisibleHTML, normalized

REPO = "riyuewuxing/InvestmentEvidenceEngine"
ROOT = "https://www.sse.com.cn/"
MAX_BYTES = 1024 * 1024
ISSUER = "中国长江航运集团南京油运股份有限公司"
NOTICES = {
    "termination": (
        "disclosure/credibility/supervision/dynamic/c/c_20160524_4118100.shtml",
        "2014-04-11", "关于终止" + ISSUER + "股票上市交易的公告",
        ('证券代码"600087"', "2013年5月14日起暂停上市", "本所决定终止该公司股票上市交易"),
    ),
    "removal": (
        "regulation/supervision/dynamic/c/c_20240321_5736672.shtml",
        "2014-06-04", "上交所提示6月5日" + '"退市长油"' + "将被摘牌",
        ("证券代码:600087", "2014年4月21日进入退市整理期交易",
         "6月4日为退市整理期的最后一个交易日", "6月5日被摘牌"),
    ),
    "approval": (
        "aboutus/mediacenter/hotandd/c/c_20181102_4671286.shtml",
        "2018-11-02", "上交所关于同意长航油运重新上市的答记者问",
        ("2018年11月2日", "2014年6月5日", "2014年8月6日在股转系统挂牌转让",
         "证券代码400061", "破产重整"),
    ),
    "relisting": (
        "disclosure/announcement/listing/c/c_20181227_4700819.shtml",
        "2018-12-28", "关于" + ISSUER + "股票重新上市的公告",
        ('证券代码为"601975"', "2014年6月5日摘牌", "2018年11月2日",
         "2019年1月8日起上市交易", "A股股本为5,023,400,024股",
         "其中1,898,551,957股"),
    ),
    "halt": (
        "disclosure/announcement/general/c/c_20190108_4706227.shtml",
        "2019-01-08", "关于ST长油(601975)盘中临时停牌的公告",
        ("2019年01月08日10时03分", "暂停ST长油(601975)交易",
         "2019年01月08日14时57分起恢复交易"),
    ),
}
PRIMARY_KEYS = tuple(NOTICES)
NOTICES.update({
    "relisting_education": (
        "https://edu.sse.com.cn/attention/c/4747935.shtml",
        "2019-01-08", "股市修炼手册之关于ST长油重新上市需要关注的那些事",
        ("上交所投教", "股票代码为601975", "首日交易不设涨跌幅限制",
         "南京油运让渡其持股总数的50%", "其他中小股东让渡其持股总数的10%",
         "停牌时间分别为09时31分至10时01分,10时03分至14时57分"),
    ),
    "relisting_rule": (
        "aboutus/mediacenter/hotandd/c/c_20150912_3988728.shtml",
        "2013-12-27", "关于修订和废止上海证券交易所退市公司股份转让系统相关业务规则的通知",
        ("重新上市首日股票交易不设涨跌幅限制",
         "最后一个转让日的成交价", "自2013年12月28日起施行"),
    ),
})
SUPPLEMENT_KEYS = ("relisting_education", "relisting_rule")


def notice_url(key: str) -> str:
    path = NOTICES[key][0]
    return path if path == "https://edu.sse.com.cn/attention/c/4747935.shtml" else ROOT + path


WINDOWS = {
    "removal": (date(2014, 6, 3), date(2014, 6, 10), date(2014, 6, 5)),
    "relisting": (date(2019, 1, 2), date(2019, 1, 11), date(2019, 1, 8)),
}
SYMBOLS = ("600087", "601975")
PROVIDERS = ("baostock", "sina", "tencent")


def parse_notice(raw: bytes, key: str) -> dict:
    if key not in NOTICES or type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("RELIST_NOTICE_SCOPE")
    _, label, title, anchors = NOTICES[key]
    parser = VisibleHTML()
    parser.feed(raw.decode("utf-8-sig", errors="strict"))
    parser.close()
    flat = normalized(" ".join(parser.parts))
    if not all(normalized(x) in flat for x in (title, label, "上海证券交易所", *anchors)):
        raise ValueError("RELIST_NOTICE_REVIEWED_FIELDS_MISMATCH")
    fields = {
        "termination": {"old_code": "600087", "suspended_from": "2013-05-14",
                        "termination_decision_date": "2014-04-11"},
        "removal": {"old_code": "600087", "delisting_period_start": "2014-04-21",
                    "last_delisting_period_session": "2014-06-04", "removal": "2014-06-05"},
        "approval": {"otc_code": "400061", "otc_reported_start": "2014-08-06",
                     "old_removal": "2014-06-05", "relisting_approval": "2018-11-02",
                     "exchange_reports_reorganization": True},
        "relisting": {"new_code": "601975", "relisting_session": "2019-01-08",
                      "total_a_shares": 5023400024, "admitted_on_first_day_shares": 1898551957,
                      "old_removal": "2014-06-05", "relisting_approval": "2018-11-02"},
        "halt": {"new_code": "601975", "halt_start": "2019-01-08T10:03:00+08:00",
                 "resume": "2019-01-08T14:57:00+08:00",
                 "clock_precision": "MINUTE_NOT_EXACT_SECONDS"},
        "relisting_education": {
            "new_code": "601975", "relisting_session": "2019-01-08",
            "first_session_daily_limit": "NONE",
            "reported_halts": [
                ["2019-01-08T09:31:00+08:00", "2019-01-08T10:01:00+08:00"],
                ["2019-01-08T10:03:00+08:00", "2019-01-08T14:57:00+08:00"],
            ],
            "clock_precision": "MINUTE_NOT_EXACT_SECONDS",
            "reorganization_reported_share_surrender_pct": {"named_shareholder": 50, "other_small_shareholders": 10},
            "individual_entitlement_verified": False,
        },
        "relisting_rule": {
            "declared_effective_date": "2013-12-28",
            "first_session_daily_limit": "NONE",
            "opening_reference_basis": "PRINCIPALLY_LAST_OTC_TRANSACTION_PRICE",
            "rule_amendment_chain_verified": False,
        },
    }[key]
    return fields | {"declared_notice_date": label, "historical_first_availability_verified": False}


def normalize_window(rows: object, window: str) -> dict[str, str]:
    start, end, _ = WINDOWS[window]
    if not isinstance(rows, list) or len(rows) > 12:
        raise ValueError("RELIST_ROWS_SCOPE")
    normalized_rows = {}
    for row in rows:
        if not isinstance(row, (tuple, list)) or len(row) != 2 or type(row[0]) is not str:
            raise ValueError("RELIST_ROW_SCHEMA")
        day = date.fromisoformat(row[0])
        if day.isoformat() != row[0] or not start <= day <= end or day.weekday() >= 5 or row[0] in normalized_rows:
            raise ValueError("RELIST_ROW_DATE")
        if type(row[1]) not in (int, float, str):
            raise ValueError("RELIST_ROW_PRICE")
        try:
            close = Decimal(str(row[1]))
        except InvalidOperation as exc:
            raise ValueError("RELIST_ROW_PRICE") from exc
        if not close.is_finite() or not 0 < close < 1_000_000 or close.as_tuple().exponent < -8:
            raise ValueError("RELIST_ROW_PRICE")
        normalized_rows[row[0]] = format(close.normalize(), "f")
    return dict(sorted(normalized_rows.items()))


def describe_rows(rows: dict[str, str], window: str, symbol: str) -> dict:
    _, _, boundary = WINDOWS[window]
    invalid = [d for d in rows if (
        symbol == "600087" and d >= "2014-06-05"
        or symbol == "601975" and d < "2019-01-08"
    )]
    return {"status": "OBSERVED" if rows else "EMPTY_RESPONSE",
            "row_count": len(rows), "session_labels": list(rows),
            "before_boundary": sum(d < boundary.isoformat() for d in rows),
            "at_or_after_boundary": sum(d >= boundary.isoformat() for d in rows),
            "incompatible_with_reported_sse_listing_dates": invalid,
            "normalized_window_sha256": hashlib.sha256(json.dumps(rows, sort_keys=True,
                separators=(",", ":")).encode()).hexdigest(),
            "row_identity": "REQUESTED_SYMBOL_ONLY", "historical_tradability_verified": False}


def _child(kind: str, key: str, symbol: str, path: Path) -> None:
    result = {"kind": kind, "key": key, "symbol": symbol, "started_at": datetime.now(UTC).isoformat()}
    try:
        if kind == "notice" and key in NOTICES and symbol == "-":
            url = notice_url(key)
            req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"})
            with build_opener(NoRedirect()).open(req, timeout=12) as response:
                if (response.status != 200 or response.geturl() != url
                        or response.headers.get("Content-Range") is not None
                        or response.headers.get("Content-Encoding", "identity").lower() not in ("identity", "")):
                    raise ValueError("RELIST_HTTP_SCOPE")
                raw = response.read(MAX_BYTES + 1)
                length = response.headers.get("Content-Length")
                if not 0 < len(raw) <= MAX_BYTES or length is not None and int(length) != len(raw):
                    raise ValueError("RELIST_BODY_SIZE")
            result |= {"url": url, "body": base64.b64encode(raw).decode("ascii"),
                       "sha256": hashlib.sha256(raw).hexdigest()}
        elif kind in PROVIDERS and key in WINDOWS and symbol in SYMBOLS:
            start, end, _ = WINDOWS[key]
            result["rows"] = normalize_window(
                _provider_rows(kind, PublicSecurity(symbol=symbol, asset_type="STOCK"), start, end), key)
        else:
            raise ValueError("RELIST_FIXED_REQUEST")
        result["status"] = "OBSERVED"
    except Exception as exc:
        message = str(exc)
        result |= {"status": "BLOCKED",
                   "error": message if re.fullmatch(r"[A-Z0-9_]{3,80}", message) else type(exc).__name__}
    result["observed_at"] = datetime.now(UTC).isoformat()
    write_worker_result(path, result, max_bytes=2*MAX_BYTES)


def observe(kind: str, key: str, symbol: str = "-") -> dict:
    before = datetime.now(UTC)
    task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.public_relisting_control",
                            "--child", kind, key, symbol), timeout_seconds=25, max_bytes=2*MAX_BYTES)
    out = {"kind": kind, "key": key, "symbol": symbol, "status": "BLOCK",
           "worker_status": task.status, "elapsed_seconds": task.elapsed_seconds, "raw_body_retained": False}
    if task.status != "OK" or task.payload is None:
        return out
    try:
        p = task.payload
        if (p["kind"], p["key"], p["symbol"]) != (kind, key, symbol):
            raise ValueError("RELIST_RECEIPT_SCOPE")
        a, b = datetime.fromisoformat(p["started_at"]), datetime.fromisoformat(p["observed_at"])
        if a.utcoffset() is None or b.utcoffset() is None or not before <= a <= b <= datetime.now(UTC):
            raise ValueError("RELIST_RECEIPT_CLOCK")
        out |= {"started_at": p["started_at"], "observed_at": p["observed_at"]}
        if p["status"] != "OBSERVED":
            return out | {"error": p.get("error", "RELIST_CHILD_BLOCK")}
        if kind == "notice":
            raw = base64.b64decode(p["body"], validate=True)
            url = notice_url(key)
            if p["url"] != url or not 0 < len(raw) <= MAX_BYTES or hashlib.sha256(raw).hexdigest() != p["sha256"]:
                raise ValueError("RELIST_RECEIPT_HASH")
            out |= {"url": url, "bytes": len(raw), "sha256": p["sha256"], "parent_rehash": "MATCH"}
            return out | {"status": "OBSERVED", "fields": parse_notice(raw, key)}
        if not isinstance(p["rows"], dict):
            raise ValueError("RELIST_RECEIPT_ROWS")
        rows = normalize_window(list(p["rows"].items()), key)
        if rows != p["rows"]:
            raise ValueError("RELIST_RECEIPT_ROWS")
        return out | describe_rows(rows, key, symbol)
    except Exception as exc:
        message = str(exc)
        return out | {"error": message if re.fullmatch(r"[A-Z0-9_]{3,80}", message) else type(exc).__name__}


def run_control() -> dict:
    # Five independent fixed documents, then sequential requests per vendor
    # (at most three vendor workers total); no alternative source or retry.
    with ThreadPoolExecutor(max_workers=3) as pool:
        notices = list(pool.map(lambda key: observe("notice", key), PRIMARY_KEYS))
        vendors = list(pool.map(lambda provider: [
            observe(provider, window, symbol) for window in WINDOWS for symbol in SYMBOLS
        ], PROVIDERS))
    complete = all(r["status"] == "OBSERVED" for r in notices)
    return {"status": "WARN" if complete else "BLOCK", "notices": notices, "vendor_windows": vendors,
            "same_issuer_not_same_listing_instance": complete,
            "ordinary_sse_gap_start": "2014-06-05" if complete else None,
            "ordinary_sse_gap_end_exclusive": "2019-01-08" if complete else None, "vendor_history_not_stitched": True,
            "historical_first_availability_verified": False, "source_independence_verified": False,
            "complete_listing_universe_verified": False, "tradability_verified": False,
            "ownership_entitlement_continuity_verified": False,
            "research_only": True, "execution_allowed": False, "decision_authority": False}


def run_supplement() -> dict:
    with ThreadPoolExecutor(max_workers=2) as pool:
        notices = list(pool.map(lambda key: observe("notice", key), SUPPLEMENT_KEYS))
    complete = all(r["status"] == "OBSERVED" for r in notices)
    return {
        "status": "WARN" if complete else "BLOCK", "notices": notices,
        "ordinary_st_rule_invalid_on_reviewed_first_session": complete,
        "price_only_continuity_is_insufficient_for_shareholder_return": complete,
        "historical_first_availability_verified": False, "individual_entitlement_verified": False,
        "actual_fill_verified": False, "research_only": True,
        "execution_allowed": False, "decision_authority": False,
    }


def main(supplement: bool = False) -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    result = (run_supplement() if supplement else run_control()) | {"executor_commit": os.environ["GITHUB_SHA"]}
    label = "PUBLIC_RELISTING_SUPPLEMENT " if supplement else "PUBLIC_RELISTING_CONTROL "
    print(label + json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if result["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "--child":
        _child(sys.argv[2], sys.argv[3], sys.argv[4], Path(sys.argv[5]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    elif sys.argv[1:] == ["--supplement"]:
        raise SystemExit(main(supplement=True))
    else:
        raise SystemExit(2)
