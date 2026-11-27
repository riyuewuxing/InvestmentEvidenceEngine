import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from investment_evidence_engine import observed_artifact_bytes as artifacts


def test_observed_file_is_same_verified_bytes_after_path_change(tmp_path: Path):
    path = tmp_path / "payload.bin"
    path.write_bytes(b"first")
    digest = hashlib.sha256(b"first").hexdigest()
    observed = artifacts.observe_file(path, expected_sha256=digest)
    path.write_bytes(b"second")
    assert observed.content == b"first"
    assert observed.sha256 == digest
    with pytest.raises(ValueError, match="DIGEST_MISMATCH"):
        artifacts.observe_file(path, expected_sha256=digest)


@pytest.mark.parametrize("bad", ["", "g"*64, "A"*64])
def test_bad_expected_digest_rejected(tmp_path, bad):
    with pytest.raises(ValueError, match="INVALID_DIGEST"):
        artifacts.observe_file(tmp_path/"absent", expected_sha256=bad)


def test_zip_hash_is_independently_recomputable_from_exact_members(tmp_path):
    (tmp_path/"assets").mkdir()
    (tmp_path/"index.html").write_bytes(b"index")
    (tmp_path/"assets"/"a.js").write_bytes(b"script")
    (tmp_path/"bundle-manifest.json").write_text("ignored")
    result = artifacts.observe_directory_zip(
        tmp_path, required="index.html", ignored=frozenset({"bundle-manifest.json"})
    )
    manifest, raw = result
    assert result == artifacts.observe_directory_zip(
        tmp_path, required="index.html", ignored=frozenset({"bundle-manifest.json"})
    )
    digest = hashlib.sha256()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert z.namelist() == ["assets/a.js", "index.html"]
        for name in z.namelist():
            value = z.read(name)
            digest.update(f"{name}:{len(value)}:{hashlib.sha256(value).hexdigest()}\n".encode())
    assert digest.hexdigest() == manifest["bundle_sha256"]
    assert hashlib.sha256(raw).hexdigest() == manifest["zip_sha256"]
    assert manifest["total_bytes"] == 11 and manifest["file_count"] == 2


def test_file_and_tree_limits_fail_closed(tmp_path):
    path = tmp_path/"index.html"
    path.write_bytes(b"12345")
    assert artifacts.observe_directory_zip(tmp_path, required="missing") is None
    with pytest.raises(ValueError, match="TOO_LARGE"):
        artifacts.observe_file(path, max_bytes=4)
    with pytest.raises(ValueError, match="FILE_LIMIT"):
        artifacts.observe_directory_zip(tmp_path, required="index.html", max_files=0)
    with pytest.raises(ValueError, match="TOO_LARGE"):
        artifacts.observe_directory_zip(tmp_path, required="index.html", max_bytes=4)


def test_tree_change_after_read_is_not_published(tmp_path, monkeypatch):
    path = tmp_path/"index.html"
    path.write_bytes(b"old")
    original = artifacts.observe_file

    def changing(*args, **kwargs):
        result = original(*args, **kwargs)
        path.write_bytes(b"longer new version")
        return result

    monkeypatch.setattr(artifacts, "observe_file", changing)
    with pytest.raises(ValueError, match="TREE_CHANGED"):
        artifacts.observe_directory_zip(tmp_path, required="index.html")


def test_symlink_fails_closed(tmp_path):
    root = tmp_path/"tree"
    root.mkdir()
    target = tmp_path/"outside"
    target.write_bytes(b"not in bundle")
    link = root/"index.html"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="NOT_REGULAR"):
        artifacts.observe_file(link)
    with pytest.raises(ValueError, match="SYMLINK"):
        artifacts.observe_directory_zip(root, required="index.html")
