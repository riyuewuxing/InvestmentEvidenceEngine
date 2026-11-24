"""Synthetic screenshot transport checks; no network or actual investment data."""
import hashlib
import json
import struct
import zlib

import pytest

from visual_qa.emit_png import emit
from visual_qa.verify_log import verify_logs

COMMIT = "a" * 40
RUN = "12345"


def _png_chunk(name: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))


def _fixture_png() -> bytes:
    # Valid minimal RGB PNG matching the native synthetic fixture's dimensions.
    width, height = 800, 480
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header)
            + _png_chunk(b"IDAT", zlib.compress((b"\x00" + b"\x10\x19\x23" * width) * height))
            + _png_chunk(b"IEND", b""))


def test_log_roundtrip_rehashes_actual_bytes(tmp_path, capsys):
    raw = _fixture_png()
    path = tmp_path / "windows-native.png"
    path.write_bytes(raw)
    emit(path, COMMIT, RUN)
    log = capsys.readouterr().out
    recovered = verify_logs([log], COMMIT, RUN)
    assert recovered == {path.name: raw}
    assert hashlib.sha256(recovered[path.name]).hexdigest() in log
    assert verify_logs(["\n".join("2026-11-24T09:00:00Z " + line for line in log.splitlines())],
                       COMMIT, RUN) == recovered


def test_log_rejects_wrong_identity_and_truncation(tmp_path, capsys):
    path = tmp_path / "windows-native.png"
    path.write_bytes(_fixture_png())
    emit(path, COMMIT, RUN)
    log = capsys.readouterr().out
    with pytest.raises(ValueError, match="scope mismatch"):
        verify_logs([log], "b" * 40, RUN)
    with pytest.raises(ValueError, match="Truncated"):
        verify_logs(["\n".join(log.splitlines()[:-1])], COMMIT, RUN)
    with pytest.raises(ValueError, match="duplicate"):
        verify_logs([log, log], COMMIT, RUN)


def test_log_rejects_forged_hash_and_unknown_screenshot(tmp_path, capsys):
    path = tmp_path / "windows-native.png"
    path.write_bytes(_fixture_png())
    emit(path, COMMIT, RUN)
    log = capsys.readouterr().out
    first, *other = log.splitlines()
    meta = json.loads(first.split(" ", 1)[1])
    meta["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Observed byte"):
        verify_logs(["\n".join(["VISUAL_QA_BEGIN " + json.dumps(meta), *other])], COMMIT, RUN)
    meta["name"] = "../private.png"
    with pytest.raises(ValueError, match="Unexpected"):
        verify_logs(["\n".join(["VISUAL_QA_BEGIN " + json.dumps(meta), *other])], COMMIT, RUN)
