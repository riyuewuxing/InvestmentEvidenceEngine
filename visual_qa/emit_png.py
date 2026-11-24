"""Bounded public screenshot transport using Actions logs, not artifact storage.

Only the three fixed synthetic screenshot names are accepted. The receiver must
decode, rehash, compare dimensions and actually view the returned image.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import struct

NAMES = {"browser-desktop.png", "browser-mobile.png", "windows-native.png"}
MAX_BYTES = 240_000
CHUNK = 1800


def emit(path: Path, commit: str, run: str) -> None:
    if path.name not in NAMES:
        raise ValueError("Screenshot name not in synthetic allowlist")
    data = path.read_bytes()
    if not (24 <= len(data) <= MAX_BYTES and data[:8] == b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid or oversized PNG")
    width, height = struct.unpack(">II", data[16:24])
    if not (0 < width <= 1600 and 0 < height <= 1000):
        raise ValueError("Unexpected screenshot dimensions")
    encoded = base64.b64encode(data).decode("ascii")
    chunks = [encoded[i:i + CHUNK] for i in range(0, len(encoded), CHUNK)]
    meta = {"name": path.name, "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "width": width, "height": height,
            "chunks": len(chunks), "executor_commit": commit, "run_id": run,
            "synthetic": True, "decision_authority": False}
    print("VISUAL_QA_BEGIN " + json.dumps(meta, separators=(",", ":")), flush=True)
    for index, chunk in enumerate(chunks):
        print(f"VISUAL_QA_CHUNK {path.name} {index:04d} {chunk}", flush=True)
    print("VISUAL_QA_END " + path.name, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("files", type=Path, nargs="+")
    args = parser.parse_args()
    if len(args.commit) != 40 or any(c not in "0123456789abcdef" for c in args.commit):
        parser.error("expected full commit SHA")
    if not args.run.isdecimal():
        parser.error("expected numeric run ID")
    if len(args.files) > 3 or len({f.name for f in args.files}) != len(args.files):
        parser.error("invalid screenshot set")
    for file in args.files:
        emit(file, args.commit, args.run)


if __name__ == "__main__":
    main()
