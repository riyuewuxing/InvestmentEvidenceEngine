"""Fixed public 300114 -> 302132 identity-event diagnostic, not an alias resolver.

Observes a reviewed official announcement and current vendor behavior around
the transition. No history stitched, no identity/return or trading admission.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import TemporaryDirectory

from .bounded_worker import run_json_worker, write_worker_result
from .historical_capture import PublicSecurity, _provider_rows
from .official_pdf_transport import retrieve_pdf_bytes, validate_pdf_shape

REPO = "riyuewuxing/InvestmentEvidenceEngine"
URL = "https://disc.static.szse.cn/disc/disk03/finalpage/2025-02-15/cedb693a-f5ee-4463-9682-ea33d406b569.PDF"
OLD, NEW = "300114", "302132"
START, CHANGE, END = date(2025, 2, 10), date(2025, 2, 17), date(2025, 2, 21)
PROVIDERS = ("baostock", "sina", "tencent")
MAX_BYTES = 4 * 1024 * 1024


def compact(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split())


def parse_reviewed_notice(pages: tuple[str, ...]) -> dict:
    if len(pages) < 2:
        raise ValueError("ALIAS_NOTICE_PAGE_SCOPE")
    first, second = map(compact, pages[:2])
    required_first = (
        "公告编号:2025-028", "关于变更公司证券简称及证券代码的实施公告",
        "深圳证券交易所创业板股票上市规则",
        "2025年2月17日开市起启用变更后的证券简称及证券代码",
        "变更后的证券代码:302132", "公司法人主体存续",
    )
    required_second = (
        "证券代码300114302132", "2025年2月17日",
        "证券类别和持有数量与代码变更完成前一致",
        "本次重大资产重组已实施完成",
    )
    if not all(x in first for x in required_first) or not all(x in second for x in required_second):
        raise ValueError("ALIAS_NOTICE_REVIEWED_FIELDS_MISMATCH")
    return {"event_type": "SECURITY_CODE_CHANGE", "announcement_number": "2025-028",
            "old_symbol": OLD, "new_symbol": NEW, "effective_session": CHANGE.isoformat(),
            "exchange": "SZSE", "board": "CHINEXT", "issuer_declares_legal_continuity": True,
            "issuer_declares_unchanged_share_count_at_code_change": True,
            "issuer_reports_prior_major_asset_restructuring": True,
            "historical_first_availability_verified": False,
            "automatic_price_stitch_allowed": False, "decision_authority": False}


def normalize_window(rows: object) -> dict[str, str]:
    if not isinstance(rows, list) or len(rows) > 12:
        raise ValueError("ALIAS_ROW_SCOPE")
    result = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != 2 or not isinstance(row[0], str):
            raise ValueError("ALIAS_ROW_SCHEMA")
        day = date.fromisoformat(row[0])
        if day.isoformat() != row[0] or not START <= day <= END or day.weekday() >= 5 or row[0] in result:
            raise ValueError("ALIAS_ROW_DATE")
        if type(row[1]) not in (str, int, float):
            raise ValueError("ALIAS_CLOSE_TYPE")
        try:
            price = Decimal(str(row[1]))
        except InvalidOperation as exc:
            raise ValueError("ALIAS_CLOSE_TYPE") from exc
        if not price.is_finite() or not 0 < price < 1_000_000 or price.as_tuple().exponent < -8:
            raise ValueError("ALIAS_CLOSE_SCOPE")
        result[row[0]] = format(price.normalize(), "f")
    return dict(sorted(result.items()))


def summarize_vendor_windows(old: dict | None, new: dict | None) -> dict:
    def describe(rows: dict | None) -> dict:
        if rows is None:
            return {"status": "UNAVAILABLE"}
        pre = [day for day in rows if day < CHANGE.isoformat()]
        post = [day for day in rows if day >= CHANGE.isoformat()]
        return {"status": "OBSERVED" if rows else "EMPTY_RESPONSE",
                "pre_change_rows": len(pre), "post_change_rows": len(post),
                "first_session": next(iter(rows), None), "last_session": next(reversed(rows), None),
                "boundary_closes": {d: rows[d] for d in ("2025-02-14", "2025-02-17") if d in rows},
                "normalized_window_sha256": hashlib.sha256(json.dumps(rows, sort_keys=True,
                    separators=(",", ":")).encode()).hexdigest()}
    result = {"old_request": describe(old), "new_request": describe(new),
              "automatic_price_stitch_allowed": False, "decision_authority": False}
    if old is not None and new is not None:
        common = sorted(set(old) & set(new))
        result |= {"overlap_sessions": len(common), "overlap_equal_closes": sum(old[d] == new[d] for d in common),
                   "cross_code_same_date_overlap": bool(common)}
    return result


def _child(kind: str, symbol: str, path: Path) -> None:
    started = datetime.now(UTC)
    payload = {"kind": kind, "symbol": symbol, "started_at": started.isoformat()}
    try:
        if kind == "notice" and symbol == OLD:
            obs = retrieve_pdf_bytes(URL, max_bytes=MAX_BYTES)
            payload |= {"url": obs.source_url, "sha256": obs.sha256,
                        "body": base64.b64encode(obs.data).decode("ascii")}
        elif kind in PROVIDERS and symbol in (OLD, NEW):
            # Deliberately observe the bounded normalized result, including
            # empty and partial windows, instead of using a min-21-day series.
            raw = _provider_rows(kind, PublicSecurity(symbol=symbol, asset_type="STOCK"), START, END)
            payload["rows"] = normalize_window(raw)
        else:
            raise ValueError("ALIAS_FIXED_REQUEST")
        payload["status"] = "OBSERVED"
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        payload |= {"status": "BLOCKED",
                    "error": msg if re.fullmatch(r"[A-Z0-9_]{3,80}", msg) else type(exc).__name__}
    payload["finished_at"] = datetime.now(UTC).isoformat()
    write_worker_result(path, payload, max_bytes=6*1024*1024)


def observe(kind: str, symbol: str) -> tuple[dict, dict | None]:
    before = datetime.now(UTC)
    result = run_json_worker((sys.executable, "-m", "investment_evidence_engine.public_symbol_change_control",
                              "--child", kind, symbol), timeout_seconds=30, max_bytes=6*1024*1024)
    out = {"kind": kind, "requested_symbol": symbol, "worker_status": result.status,
           "elapsed_seconds": result.elapsed_seconds, "status": "BLOCKED", "raw_body_retained": False}
    if result.status != "OK" or result.payload is None:
        return out, None
    try:
        p = result.payload
        if p["kind"] != kind or p["symbol"] != symbol:
            raise ValueError("ALIAS_RECEIPT_IDENTITY")
        start, finish = datetime.fromisoformat(p["started_at"]), datetime.fromisoformat(p["finished_at"])
        if start.utcoffset() is None or finish.utcoffset() is None or not before <= start <= finish <= datetime.now(UTC):
            raise ValueError("ALIAS_RECEIPT_CLOCK")
        out |= {"started_at": p["started_at"], "finished_at": p["finished_at"]}
        if p["status"] != "OBSERVED":
            out["error"] = p.get("error", "ALIAS_CHILD_BLOCKED")
            return out, None
        if kind == "notice":
            from pypdf import PdfReader

            raw = base64.b64decode(p["body"], validate=True)
            if p["url"] != URL or hashlib.sha256(raw).hexdigest() != p["sha256"]:
                raise ValueError("ALIAS_NOTICE_HASH")
            validate_pdf_shape(raw, max_bytes=MAX_BYTES)
            with TemporaryDirectory() as temp:
                f = Path(temp)/"notice.pdf"
                f.write_bytes(raw)
                check = f.read_bytes()
                if check != raw:
                    raise ValueError("ALIAS_NOTICE_REOPEN_HASH")
            out |= {"url": URL, "bytes": len(check), "sha256": p["sha256"],
                    "parent_rehash": "MATCH", "temporary_rehash": "MATCH"}
            reader = PdfReader(io.BytesIO(check), strict=True)
            if reader.is_encrypted or not 2 <= len(reader.pages) <= 20:
                raise ValueError("ALIAS_NOTICE_PAGE_SCOPE")
            fields = parse_reviewed_notice(tuple(page.extract_text() or "" for page in reader.pages[:2]))
            return out | {"status": "OBSERVED", "fields": fields}, fields
        rows = p["rows"]
        if not isinstance(rows, dict):
            raise ValueError("ALIAS_RECEIPT_ROWS")
        normalized = normalize_window([[d, price] for d, price in rows.items()])
        if normalized != rows:
            raise ValueError("ALIAS_RECEIPT_ROWS")
        return out | {"status": "OBSERVED" if rows else "EMPTY_RESPONSE", "row_count": len(rows),
                      "row_identity_scope": "REQUESTED_SYMBOL_NOT_INDEPENDENT_LISTING_INSTANCE",
                      "price_basis": "VENDOR_REPORTED_UNADJUSTED_CLOSE"}, normalized
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        out["error"] = msg if re.fullmatch(r"[A-Z0-9_]{3,80}", msg) else type(exc).__name__
        return out, None


def run_control() -> dict:
    tasks = [("notice", OLD)] + [(p, s) for p in PROVIDERS for s in (OLD, NEW)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda task: observe(*task), tasks))
    notices = results[0][0]
    vendors = {}
    for i, provider in enumerate(PROVIDERS):
        old, new = results[1+2*i:3+2*i]
        vendors[provider] = {"old_receipt": old[0], "new_receipt": new[0],
                             "comparison": summarize_vendor_windows(old[1], new[1])}
    return {"status": "WARN" if notices["status"] == "OBSERVED" else "BLOCK",
            "notice": notices, "vendors": vendors,
            "window": [START.isoformat(), END.isoformat()], "change_session": CHANGE.isoformat(),
            "source_independence_verified": False, "historical_availability_verified": False,
            "automatic_price_stitch_allowed": False, "listing_instance_identity_verified": False,
            "research_only": True, "execution_allowed": False, "decision_authority": False}


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    report = run_control() | {"executor_commit": os.environ["GITHUB_SHA"]}
    print("PUBLIC_SYMBOL_CHANGE_CONTROL "+json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--child":
        _child(sys.argv[2], sys.argv[3], Path(sys.argv[4]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
