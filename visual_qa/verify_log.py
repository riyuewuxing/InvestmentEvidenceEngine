"""Recover verified synthetic PNG screenshots from downloaded Actions job logs.

Example:
    python visual_qa/verify_log.py --commit <full SHA> --run <run ID> \
        --log browser.log --log windows.log --out-dir ./visual-results

No network, private checkout, or artifact-store access is required.
Only the fixed synthetic fixture names and dimensions are accepted.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import struct
from pathlib import Path

EXPECTED = {
    "browser-desktop.png": (1200, 760),
    "browser-mobile.png": (390, 844),
    "windows-native.png": (800, 480),
}
MAX_LOG_BYTES = 2_000_000
MAX_PNG_BYTES = 240_000
CHUNK_SIZE = 1800
PREFIX = "VISUAL_QA_"


def verify_logs(logs: list[str], commit: str, run: str) -> dict[str, bytes]:
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None or not run.isdecimal():
        raise ValueError("A full commit SHA and numeric run ID are required")
    results: dict[str, bytes] = {}
    for log in logs:
        if len(log.encode("utf-8")) > MAX_LOG_BYTES:
            raise ValueError("Log exceeds byte budget")
        meta = None
        chunks: list[str] = []
        for line in log.splitlines():
            # GitHub's UTC timestamp prefix is not part of the record.
            record = re.search(r"(?:^|\s)(VISUAL_QA_(?:BEGIN|CHUNK|END) .+)$", line)
            if record is None:
                continue
            kind, payload = record.group(1).split(" ", 1)
            if kind == PREFIX + "BEGIN":
                if meta is not None:
                    raise ValueError("Nested screenshot record")
                meta = json.loads(payload)
                if not isinstance(meta, dict):
                    raise ValueError("Invalid screenshot metadata")
                name = meta.get("name")
                if not isinstance(name, str) or name not in EXPECTED or name in results:
                    raise ValueError("Unexpected or duplicate screenshot")
                if (meta.get("executor_commit") != commit or meta.get("run_id") != run
                        or meta.get("synthetic") is not True
                        or meta.get("decision_authority") is not False):
                    raise ValueError("Screenshot provenance or scope mismatch")
                if ((meta.get("width"), meta.get("height")) != EXPECTED[name]
                        or type(meta.get("bytes")) is not int
                        or not 24 <= meta["bytes"] <= MAX_PNG_BYTES
                        or type(meta.get("chunks")) is not int
                        or not 1 <= meta["chunks"] <= 180):
                    raise ValueError("Screenshot dimensions or size out of bounds")
                chunks = []
            elif kind == PREFIX + "CHUNK":
                if meta is None:
                    raise ValueError("Chunk outside screenshot record")
                match = re.fullmatch(r"(\S+) (\d{4}) ([A-Za-z0-9+/=]+)", payload)
                if (match is None or match[1] != meta["name"]
                        or int(match[2]) != len(chunks)
                        or len(match[3]) > CHUNK_SIZE or len(chunks) >= meta["chunks"]):
                    raise ValueError("Unexpected chunk identity, order or length")
                chunks.append(match[3])
            elif kind == PREFIX + "END":
                if meta is None or payload != meta["name"] or len(chunks) != meta["chunks"]:
                    raise ValueError("Incomplete screenshot")
                data = base64.b64decode("".join(chunks), validate=True)
                if (len(data) != meta["bytes"]
                        or hashlib.sha256(data).hexdigest() != meta.get("sha256")
                        or data[:8] != b"\x89PNG\r\n\x1a\n"
                        or data[12:16] != b"IHDR"
                        or struct.unpack(">II", data[16:24]) != EXPECTED[payload]):
                    raise ValueError("Observed byte or PNG header mismatch")
                results[payload] = data
                meta = None
                chunks = []
        if meta is not None:
            raise ValueError("Truncated screenshot record")
    if not results:
        raise ValueError("No complete screenshots")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--log", required=True, action="append", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--expected", nargs="+", choices=sorted(EXPECTED), default=sorted(EXPECTED))
    args = parser.parse_args()
    if len(args.log) > 3 or any(p.stat().st_size > MAX_LOG_BYTES for p in args.log):
        parser.error("Log count or size out of bounds")
    results = verify_logs([p.read_text(encoding="utf-8") for p in args.log], args.commit, args.run)
    if set(results) != set(args.expected):
        raise ValueError("Actual screenshot set differs from expected set")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if any((args.out_dir / name).exists() for name in results):
        raise FileExistsError("Refusing to overwrite existing screenshot")
    for name, data in results.items():
        with (args.out_dir / name).open("xb") as file:
            file.write(data)
        print(json.dumps({
            "name": name, "observed_sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "dimensions": EXPECTED[name],
            "run_id": args.run, "executor_commit": args.commit,
            "observed_bytes_verified": True, "visual_inspection_still_required": True,
        }))


if __name__ == "__main__":
    main()
