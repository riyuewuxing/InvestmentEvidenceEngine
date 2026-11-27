"""Strict CSI300 point snapshots and reconciliation; not continuous PIT membership.

Source date is a label on the observed workbook. Archive commit metadata and
current capture are distinct clocks. A 300-code snapshot is not a security
master, a historical weight series, or evidence of a complete change stream.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, localcontext

INDEX_CODE = "000300"
COUNT = 300
OUT = tuple("000661 000786 000876 000983 002252 002459 002601 300347 300759 300782 300979 600161 600377 601236 601298 601808 603195 688169 688187".split())
IN = tuple("000657 000988 001280 002202 002353 002532 002558 002602 002837 300450 301165 301308 600118 600221 600549 601727 688072 688183 688521".split())
# Deliberately narrow aliases. Header matching never infers an unlabeled positional column.
HEADER_ALIASES = {
    "date": {"日期date", "日期", "date"},
    "index": {"指数代码indexcode", "指数代码", "indexcode"},
    "index_name": {"指数名称indexname", "指数名称", "indexname"},
    "code": {"成份券代码constituentcode", "成分券代码constituentcode", "成份券代码", "成分券代码"},
    "name": {"成份券名称constituentname", "成分券名称constituentname", "成份券名称", "成分券名称"},
    "exchange": {"交易所exchange", "交易所名称exchange", "交易所", "交易所名称"},
    "weight": {"权重weight", "权重(%)weight(%)", "权重(%)weight", "权重weight(%)", "权重(%)", "权重", "weight", "weight(%)"},
}
EXCHANGES = {"上海": "SH", "上海证券交易所": "SH", "上交所": "SH", "深圳": "SZ",
             "深圳证券交易所": "SZ", "深交所": "SZ"}
WEIGHT_SUM_TOLERANCE_PP = Decimal("0.15")


def compact(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split())


def _header(value: object) -> str:
    return compact(value).lower() if isinstance(value, str) else ""


def _integer_text(value: object) -> str:
    if type(value) is int:
        return str(value)
    if type(value) is float and value.is_integer():
        return str(int(value))
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return value
    raise ValueError("INDEX_INTEGER_CELL")


def code_cell(value: object) -> str:
    raw = _integer_text(value)
    if not 1 <= len(raw) <= 6:
        raise ValueError("INDEX_CODE_CELL")
    return raw.zfill(6)


def date_cell(value: object) -> date:
    if type(value) is date:
        return value
    if type(value) is datetime:
        if value.hour or value.minute or value.second or value.microsecond or value.tzinfo:
            raise ValueError("INDEX_DATE_CELL")
        return value.date()
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return date.fromisoformat(value)
    raw = _integer_text(value)
    if len(raw) != 8:
        raise ValueError("INDEX_DATE_CELL")
    return date.fromisoformat(f"{raw[:4]}-{raw[4:6]}-{raw[6:]}")


def expected_exchange(code: str) -> str:
    if re.fullmatch(r"(?:60[0135]|688|689)[0-9]{3}", code):
        return "SH"
    if re.fullmatch(r"(?:00[0123]|30[01])[0-9]{3}", code):
        return "SZ"
    raise ValueError("INDEX_SECURITY_CODE_SCOPE")


def _weight(value: object) -> Decimal:
    if type(value) not in (int, float, str):
        raise ValueError("INDEX_WEIGHT_CELL")
    raw = str(value)
    if not re.fullmatch(r"(?:0|[1-9][0-9]{0,2})(?:\.[0-9]{1,8})?", raw):
        raise ValueError("INDEX_WEIGHT_CELL")
    v = Decimal(raw)
    if not 0 < v <= 100:
        raise ValueError("INDEX_WEIGHT_DOMAIN")
    return v


def parse_rows(rows: list[list], *, weighted: bool, latest_label: date) -> dict:
    """Validate source-labeled rows, without silently dropping or filling any row."""
    if type(weighted) is not bool or type(latest_label) is not date:
        raise ValueError("INDEX_PARSE_SCOPE")
    if len(rows) != COUNT+1 or not 9 <= len(rows[0]) <= 12:
        raise ValueError("INDEX_SNAPSHOT_SHAPE")
    header = [_header(v) for v in rows[0]]
    if not all(header) or len(set(header)) != len(header):
        raise ValueError("INDEX_HEADER_DUPLICATE_OR_EMPTY")
    required = ("date", "index", "index_name", "code", "name", "exchange") + (("weight",) if weighted else ())
    positions = {}
    for key in required:
        candidates = [i for i, h in enumerate(header) if h in HEADER_ALIASES[key]]
        if len(candidates) != 1:
            raise ValueError("INDEX_HEADER_" + key.upper())
        positions[key] = candidates[0]
    if len(set(positions.values())) != len(required):
        raise ValueError("INDEX_HEADER_AMBIGUOUS")
    if not weighted and any(h in HEADER_ALIASES["weight"] for h in header):
        raise ValueError("INDEX_MEMBERSHIP_HAS_WEIGHT_COLUMN")
    dates = set()
    codes, names, exchanges, weights = [], {}, {}, {}
    for row in rows[1:]:
        if len(row) != len(header):
            raise ValueError("INDEX_ROW_WIDTH")
        val = {key: row[i] for key, i in positions.items()}
        day = date_cell(val["date"])
        if day > latest_label or day.year < 2005:
            raise ValueError("INDEX_LABEL_AFTER_CAPTURE")
        dates.add(day)
        if (code_cell(val["index"]) != INDEX_CODE or not isinstance(val["index_name"], str)
                or compact(val["index_name"]) not in {"沪深300", "沪深300指数"}):
            raise ValueError("INDEX_IDENTITY_MISMATCH")
        code = code_cell(val["code"])
        if code in names:
            raise ValueError("INDEX_DUPLICATE_SECURITY")
        name = val["name"]
        if not isinstance(name, str) or not compact(name) or len(name) > 100:
            raise ValueError("INDEX_SECURITY_NAME")
        exchange = val["exchange"]
        if not isinstance(exchange, str) or EXCHANGES.get(compact(exchange)) != expected_exchange(code):
            raise ValueError("INDEX_SECURITY_EXCHANGE")
        codes.append(code)
        names[code] = compact(name)
        exchanges[code] = EXCHANGES[compact(exchange)]
        if weighted:
            weights[code] = _weight(val["weight"])
    if len(dates) != 1:
        raise ValueError("INDEX_MIXED_LABEL_DATES")
    result = {"index_code": INDEX_CODE, "label_day": next(iter(dates)).isoformat(),
              "codes": codes, "names": names, "exchanges": exchanges, "weights": weights}
    if weighted and abs(sum(weights.values())-Decimal(100)) > WEIGHT_SUM_TOLERANCE_PP:
        raise ValueError("INDEX_WEIGHT_SUM_OUTSIDE_REVIEWED_TOLERANCE")
    return result


def parse_csv(raw: bytes) -> list[str]:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 8192:
        raise ValueError("INDEX_CSV_SIZE")
    lines = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True))
    if (len(lines) != COUNT+1 or lines[0] != ["code"]
            or any(len(row) != 1 or not re.fullmatch(r"[0-9]{6}", row[0]) for row in lines[1:])):
        raise ValueError("INDEX_CSV_SCHEMA")
    codes = [row[0] for row in lines[1:]]
    if len(set(codes)) != COUNT:
        raise ValueError("INDEX_CSV_DUPLICATE")
    return codes


def git_blob_sha1(raw: bytes) -> str:
    if not isinstance(raw, bytes) or not raw:
        raise ValueError("INDEX_RAW_BYTES")
    return hashlib.sha1(b"blob "+str(len(raw)).encode("ascii")+b"\x00"+raw,
                        usedforsecurity=False).hexdigest()


def digest_codes(codes: list[str]) -> str:
    if len(codes) != COUNT or len(set(codes)) != COUNT or any(not re.fullmatch(r"[0-9]{6}", c) for c in codes):
        raise ValueError("INDEX_CODE_SET")
    return hashlib.sha256(json.dumps(sorted(codes), separators=(",", ":")).encode()).hexdigest()


def parse_notice(page: str) -> dict:
    text = compact(page)
    heading, end = "沪深300指数样本调整名单:", "中证500指数样本调整名单:"
    if text.count(heading) != 1 or text.count(end) != 1:
        raise ValueError("INDEX_NOTICE_SECTION")
    section = text.split(heading, 1)[1].split(end, 1)[0]
    if not all(marker in section for marker in ("调出名单", "调入名单", "证券代码", "证券名称")):
        raise ValueError("INDEX_NOTICE_HEADERS")
    numbers = re.findall(r"(?<![0-9])[0-9]{6}(?![0-9])", section)
    if tuple(numbers[::2]) != OUT or tuple(numbers[1::2]) != IN:
        raise ValueError("INDEX_NOTICE_REVIEWED_CODE_PAIRS_MISMATCH")
    return {"removed": list(OUT), "added": list(IN), "row_pairs": len(OUT),
            "reviewed_page": 1, "identity_join_key": "SIX_DIGIT_SECURITY_CODE",
            "source_publication_clock_verified": False}


def membership_difference(before: dict, after: dict, *, notice: dict | None = None) -> dict:
    if before["index_code"] != INDEX_CODE or after["index_code"] != INDEX_CODE:
        raise ValueError("INDEX_DIFF_IDENTITY")
    if date.fromisoformat(before["label_day"]) >= date.fromisoformat(after["label_day"]):
        raise ValueError("INDEX_DIFF_LABEL_ORDER")
    a, b = before["codes"], after["codes"]
    digest_codes(a)
    digest_codes(b)
    a, b = set(a), set(b)
    removed, added = sorted(a-b), sorted(b-a)
    out = {"before_label": before["label_day"], "after_label": after["label_day"],
           "removed": removed, "added": added, "common_members": len(a & b),
           "member_replacement_fraction": len(added)/COUNT,
           "member_replacement_is_not_weighted_turnover": True,
           "complete_intermediate_event_stream_verified": False}
    if notice is not None:
        out["reviewed_notice_set_match"] = (removed == sorted(notice["removed"])
                                             and added == sorted(notice["added"]))
    return out


def snapshot_summary(snapshot: dict) -> dict:
    codes = snapshot["codes"]
    output = {"index_code": INDEX_CODE, "source_label_day": snapshot["label_day"],
              "members": len(codes), "code_set_sha256": digest_codes(codes),
              "exchange_counts": {venue: list(snapshot["exchanges"].values()).count(venue)
                                  for venue in ("SH", "SZ")},
              "code_001280_reported_name": snapshot["names"].get("001280"),
              "complete_listing_instance_identity_verified": False,
              "historical_availability_verified": False,
              "complete_interval_membership_verified": False,
              "decision_authority": False}
    weights = snapshot["weights"]
    if weights:
        if set(weights) != set(codes):
            raise ValueError("INDEX_WEIGHT_IDENTITY_SCOPE")
        with localcontext() as ctx:
            ctx.prec = 40
            total = sum(weights.values())
            if abs(total-Decimal(100)) > WEIGHT_SUM_TOLERANCE_PP:
                raise ValueError("INDEX_WEIGHT_SUM_OUTSIDE_REVIEWED_TOLERANCE")
            ordered = sorted(weights.items(), key=lambda row: (-row[1], row[0]))
            hhi = sum((v/total)**2 for v in weights.values())
            output |= {"reported_weight_sum_pct": str(total),
                       "top10_reported_weight_pct": str(sum(v for _, v in ordered[:10])),
                       "largest_weight_code": ordered[0][0], "largest_weight_pct": str(ordered[0][1]),
                       "hhi_normalized_by_reported_sum": str(hhi.quantize(Decimal("0.00000001"))),
                       "effective_member_count_from_reported_weights": str((1/hhi).quantize(Decimal("0.01"))),
                       "weights_are_snapshot_only": True}
    return output
