"""Fixed public XML and externally archived release byte comparison, no redistribution."""
import json
import sys
from base64 import b64decode, b64encode
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
from zipfile import ZipFile

import httpx

from investment_evidence_engine.bounded_worker import run_json_worker, write_worker_result
from investment_evidence_engine.szse_pcf import parse_szse_pcf

CASES = {
    "20260907": ("159607", 4800604, "9008f3d0aef39345bdc86ccc04b626828be88ebf09d5f3b4733466b185a68ac2", "2026-09-07T06:33:03Z", 548295938),
    "20260908": ("159607", 4803890, "fd9247bcdb6dcf250cab5cbc595761f1e6022db9891e507d6847af3aeb0f7d51", "2026-09-08T11:10:52Z", 550352692),
    "20260827": ("159696", 4754468, "c29e40aa973c3f1d42bf009e86cb509b159db638fdfb6d83a9414efdee223dc9", "2026-08-27T11:28:43Z", 532208940),
    "20260828": ("159696", 4775244, "f0d14f82cc1900458779d6e1083b76674882c4f798983f0493bd6c52ba8ca58b", "2026-08-28T08:57:24Z", 533531197),
}

# SHA256 of each XML matched to its pinned archive member by run 45967529896.
XML_PINS = {
    "20260907": "eb0bbf04dd88e55884e5d8aa242080037a2d81781f78afb10ea0742dd45fa575",
    "20260908": "2bf2f3ea963498c07d5073833285c98415e5c731b4994cb966f8b3b5526c5753",
    "20260827": "e61e8e0fbc729ca59a2e096b154f23c7bfd8f29bb822c8692f82b21b56554d42",
    "20260828": "9f9a193619d363b6f0881dcdd70bf4ce58e8b31227cc8273570e8179cb27533b",
}


def fetch(key, route):
    symbol, size, _, _, _ = CASES[key]
    if route == "archive":
        url = f"https://github.com/y1han/china_etf_pcf/releases/download/{key}/{key}.zip"
        limit = size
    else:
        url = f"https://reportdocs.static.szse.cn/files/text/ETFDown/pcf_{symbol}_{key}.xml"
        limit = 1024 * 1024
    try:
        with httpx.Client(timeout=6.0, follow_redirects=False) as client:
            with client.stream("GET", url) as response:
                if route == "archive" and response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location", "")
                    target = urlparse(location)
                    if target.scheme != "https" or target.hostname not in (
                        "release-assets.githubusercontent.com", "objects.githubusercontent.com"
                    ) or target.username or target.password or target.port not in (None, 443):
                        return {"status": "REDIRECT_BLOCKED"}
                else:
                    return read(response, limit)
            with client.stream("GET", location) as response:
                return read(response, limit)
    except Exception as exc:
        return {"status": "FETCH_FAILED", "error_type": type(exc).__name__}


def read(response, limit):
    if response.status_code != 200:
        return {"status": "HTTP_NON_200", "http_status": response.status_code}
    chunks = bytearray()
    for chunk in response.iter_bytes(65536):
        if len(chunks) + len(chunk) > limit:
            return {"status": "SIZE_LIMIT"}
        chunks.extend(chunk)
    return {"status": "RECEIVED", "body_b64": b64encode(chunks).decode("ascii")}


def archive_member(raw, symbol):
    with ZipFile(BytesIO(raw)) as z:
        infos = z.infolist()
        if len(infos) > 5000:
            raise ValueError("too many members")
        target = f"SZ/{symbol}.SZ.xml"
        found = [i for i in infos if i.filename == target]
        if len(found) != 1:
            raise ValueError("selected member absent/duplicate")
        if not 0 < found[0].file_size <= 1024 * 1024:
            raise ValueError("member size limit")
        with z.open(found[0]) as stream:
            body = stream.read(1024 * 1024 + 1)
        if len(body) != found[0].file_size:
            raise ValueError("member length mismatch")
        return body


def observe(task):
    key, route = task
    symbol, size, expected, published, asset_id = CASES[key]
    result = run_json_worker(
        (sys.executable, "-m", "investment_evidence_engine.public_szse_pcf_archive_control", "--worker", key, route),
        timeout_seconds=35, max_bytes=8 * 1024 * 1024,
    )
    out = {"date": key, "symbol": symbol, "route": route, "worker_status": result.status,
           "elapsed_seconds": result.elapsed_seconds, "raw_body_retained": False}
    if route == "archive":
        out.update(archive_release_published_at=published, archive_asset_id=asset_id,
                   expected_archive_sha256=expected)
    if result.status != "OK" or not result.payload:
        return out | {"status": "BLOCK"}
    payload = dict(result.payload)
    body = payload.pop("body_b64", None)
    if body is None:
        return out | payload | {"status": "BLOCK", "fetch_status": payload.get("status")}
    try:
        raw = b64decode(body, validate=True)
        digest = sha256(raw).hexdigest()
        out.update(download_bytes=len(raw), download_sha256=digest)
        if route == "archive":
            if len(raw) != size or digest != expected:
                return out | {"status": "BLOCK", "error": "ARCHIVE_PIN_MISMATCH"}
            out["archive_pin"] = "MATCH"
            raw = archive_member(raw, symbol)
        out["xml_sha256"] = sha256(raw).hexdigest()
        out["xml_bytes"] = len(raw)
        if route == "official_pinned":
            if out["xml_sha256"] != XML_PINS[key]:
                return out | {"status": "BLOCK", "error": "PINNED_XML_MISMATCH"}
            out["prior_xml_pin"] = "MATCH"
        # Only normalized fixed fields are emitted.
        out["fields"] = parse_szse_pcf(raw, symbol=symbol, session=date.fromisoformat(
            f"{key[:4]}-{key[4:6]}-{key[6:]}"))
        return out | {"status": "OBSERVED"}
    except Exception as exc:
        return out | {"status": "BLOCK", "error": str(exc)[:160], "error_type": type(exc).__name__}


def main():
    if len(sys.argv) == 5 and sys.argv[1] == "--worker":
        key, route, dest = sys.argv[2:]
        write_worker_result(Path(dest), fetch(key, route), max_bytes=8 * 1024 * 1024)
        return
    replay = sys.argv[1:] == ["--pinned-replay"]
    routes = ("official_pinned",) if replay else ("archive", "official")
    tasks = [(key, route) for key in CASES for route in routes]
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(observe, tasks))
    comparisons = []
    for key in (() if replay else CASES):
        a, b = [r for r in rows if r["date"] == key]
        comparisons.append({"date": key, "byte_match": (
            a["xml_sha256"] == b["xml_sha256"] if "xml_sha256" in a and "xml_sha256" in b else None
        ), "fields_match": (
            a["fields"] == b["fields"] if "fields" in a and "fields" in b else None
        )})
    evidence_complete = all(row["status"] == "OBSERVED" for row in rows) and (
        replay or all(x["byte_match"] is True and x["fields_match"] is True for x in comparisons)
    )
    print("PUBLIC_SZSE_PCF_ARCHIVE " + json.dumps({
        "status": "WARN" if evidence_complete else "BLOCK",
        "observed_at": datetime.now(UTC).isoformat(), "rows": rows,
        "comparisons": comparisons, "pinned_replay": replay,
        "historical_first_availability_verified": False,
        "archive_metadata_is_not_exchange_publication_time": True,
        "decision_authority": False, "raw_body_retained": False,
    }, ensure_ascii=False, sort_keys=True, allow_nan=False))
    if not evidence_complete:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
