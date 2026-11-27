"""Fixed issuer-described 2025 ST withdrawal and suspension, retrospective only."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from investment_evidence_engine.action_reference import _rows
from investment_evidence_engine.bounded_worker import run_json_worker, write_worker_result
from investment_evidence_engine.execution_obstruction import inspect_explicit_eligibility
from investment_evidence_engine.issuer_revision_control import normalize_text
from investment_evidence_engine.market_calendar import scheduled_days
from investment_evidence_engine.official_pdf_transport import retrieve_pdf_bytes
from investment_evidence_engine.retrospective_control import acquire_tencent

REPO = "riyuewuxing/InvestmentEvidenceEngine"
CODE = "sz.002748"
FIRST, LAST = date(2025, 5, 12), date(2025, 5, 30)
SUSPEND, RESUME = date(2025, 5, 21), date(2025, 5, 22)
URL = "https://disc.static.szse.cn/download/disc/disk03/finalpage/2025-05-20/d0ee17e2-6c8c-4014-9b75-708e5149e351.PDF"
FIELDS = ["date", "code", "open", "high", "low", "close", "preclose", "volume",
          "adjustflag", "tradestatus", "isST"]


def child_notice(raw_target: Path, out: Path) -> None:
    import io

    from pypdf import PdfReader

    doc = retrieve_pdf_bytes(URL)
    raw_target.write_bytes(doc.data)
    reader = PdfReader(io.BytesIO(doc.data), strict=True)
    if reader.is_encrypted or len(reader.pages) != 4:
        raise ValueError("ST_NOTICE_PAGE_SCOPE")
    pages = {i: normalize_text(reader.pages[i].extract_text() or "") for i in (0, 3)}
    first = ("证券代码:002748", "2025-024", "江西世龙实业股份有限公司", "关于撤销其他风险警示暨停复牌的公告",
             "2025年5月21日停牌一天", "2025年5月22日开市起复牌", "由5%变为10%")
    last = ("已获得深圳证券交易所审核同意", "2025年5月21日开市起停牌一天",
            "2025年5月22日开市起撤销其他风险警示并恢复交易", "2025年5月20日")
    markers = [m in pages[0] for m in first] + [m in pages[3] for m in last]
    write_worker_result(out, {"status": "OBSERVED" if all(markers) else "BLOCK",
        "url": doc.source_url, "source_sha256": doc.sha256, "source_bytes": len(doc.data),
        "observed_at": doc.retrieved_at, "page_count": len(reader.pages), "marker_matches": markers,
        "page_text_sha256": {str(i): hashlib.sha256(v.encode()).hexdigest() for i, v in pages.items()},
        "historical_first_availability_verified": False})


def child_rows(out: Path) -> None:
    import baostock as bs

    started = datetime.now(UTC)
    if bs.login().error_code != "0":
        raise ValueError("LOGIN")
    try:
        rows = _rows(bs.query_history_k_data_plus(CODE, ",".join(FIELDS), start_date=FIRST.isoformat(),
                     end_date=LAST.isoformat(), frequency="d", adjustflag="3"), FIELDS, 64)
    finally:
        bs.logout()
    write_worker_result(out, {"started": started.isoformat(), "observed_at": datetime.now(UTC).isoformat(),
                              "rows": rows})


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    report = {"status": "BLOCK", "executor_commit": os.environ["GITHUB_SHA"], "subject": CODE,
              "first": FIRST.isoformat(), "last": LAST.isoformat(), "decision_authority": False,
              "pit_safe": False, "execution_allowed": False, "raw_sources_retained": False}
    stage = "ISSUER_NOTICE"
    try:
        with TemporaryDirectory() as folder:
            target = Path(folder) / "notice.pdf"
            task = run_json_worker((sys.executable, __file__, "--notice", str(target)),
                                   timeout_seconds=35, max_bytes=65536)
            notice = (task.payload or {"status": "BLOCK"}) | {
                "worker_status": task.status, "elapsed_seconds": task.elapsed_seconds}
            prior_sha = "3e81336b3b2a9826aa3a34a8065582bad8b2c118ded51364159d43225caa9f99"
            match = (target.is_file() and target.stat().st_size == notice.get("source_bytes")
                     and hashlib.sha256(target.read_bytes()).hexdigest() == notice.get("source_sha256") == prior_sha)
            notice["parent_rehash"] = "MATCH" if match else "NOT_VERIFIED"
            report["notice"] = notice
            if task.status != "OK" or notice["status"] != "OBSERVED" or not match:
                raise ValueError("ST_NOTICE_BLOCK")
        stage = "BAOSTOCK_STATUS"
        task = run_json_worker((sys.executable, __file__, "--rows"), timeout_seconds=40, max_bytes=65536)
        report["baostock_worker"] = {"status": task.status, "elapsed_seconds": task.elapsed_seconds}
        if task.status != "OK" or task.payload is None:
            raise ValueError("ST_STATUS_BLOCK")
        data = task.payload
        start, end = (datetime.fromisoformat(data[k]) for k in ("started", "observed_at"))
        if start.utcoffset() is None or end.utcoffset() is None or not start <= end <= datetime.now(UTC):
            raise ValueError("ST_STATUS_CLOCK")
        rows = data["rows"]
        report["baostock"] = {"rows": len(rows), "observed_at": end.isoformat(),
            "normalized_rows_sha256": hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest(),
            "status_counts": {flag: sum(row[9] == flag for row in rows) for flag in ("0", "1")},
            "boundary_statuses": [{"date": row[0], "trade": row[9], "st": row[10],
                                   "volume_missing": row[7] == "",
                                   "zero_volume": None if row[7] == "" else Decimal(row[7]) == 0}
                                  for row in rows if row[0] in ("2025-05-20", "2025-05-21", "2025-05-22")]}
        stage = "TENCENT_RAW"
        other, info = acquire_tencent(CODE[3:], FIRST, LAST)
        report["tencent"] = info
        if other is None:
            raise ValueError("ST_TENCENT_BLOCK")
        sessions = tuple(r.day for r in scheduled_days(FIRST, LAST) if r.is_trading_day)
        regimes = {d: "SUSPENDED" if d == SUSPEND else "ST_5" if d < RESUME else "ORDINARY_10" for d in sessions}
        other_ohlc = {row.date.date(): tuple(Decimal(str(getattr(row, k))) for k in ("open", "high", "low", "close"))
                      for row in other.itertuples(index=False)}
        stage = "ELIGIBILITY_COMPARE"
        report["diagnostic"] = inspect_explicit_eligibility(rows, identity=CODE, sessions=sessions,
                regimes=regimes, other_ohlc=other_ohlc, event_references={})
        report["status"] = "WARN"
    except (ValueError, TypeError, KeyError, RuntimeError, ArithmeticError, IndexError) as exc:
        report["failed_stage"] = stage
        report["blocker"] = str(exc) if isinstance(exc, ValueError) and str(exc).isascii() and str(exc).isupper() else type(exc).__name__
    print("PUBLIC_ST_TRANSITION " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--notice":
        child_notice(Path(sys.argv[2]), Path(sys.argv[3]))
    elif len(sys.argv) == 3 and sys.argv[1] == "--rows":
        child_rows(Path(sys.argv[2]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
