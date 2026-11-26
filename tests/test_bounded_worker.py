import json
import subprocess
import sys
import time

import pytest

from investment_evidence_engine.bounded_worker import run_json_worker, write_worker_result


def command(source):
    return (sys.executable, "-c", source)


def test_worker_success_and_noise_is_not_result():
    r = run_json_worker(command(
        "import sys,json; from pathlib import Path; print('noise'*10000); "
        "Path(sys.argv[-1]).write_text(json.dumps({'n': 0, 'missing': None}))"
    ), timeout_seconds=10)
    assert r.status == "OK" and r.payload == {"n": 0, "missing": None}
    assert r.exit_code == 0


def test_actual_hung_process_is_killed(tmp_path):
    marker = tmp_path / "unexpected-late-output"
    r = run_json_worker(command(
        "import time; from pathlib import Path; time.sleep(4); "
        f"Path({str(marker)!r}).write_text('late')"
    ), timeout_seconds=0.4)
    assert r.status == "WATCHDOG_TIMEOUT"
    assert r.exit_code is not None
    assert r.elapsed_seconds < 3.9
    time.sleep(0.2)
    assert not marker.exists()


def test_failure_and_start_failure():
    r = run_json_worker(command("raise SystemExit(7)"), timeout_seconds=10)
    assert r.status == "WORKER_FAILED" and r.exit_code == 7 and r.payload is None
    missing = run_json_worker(("definitely-not-a-real-executable-58731",), timeout_seconds=2)
    assert missing.status == "START_FAILED"


@pytest.mark.parametrize("raw", ["[]", "{", '{"x":NaN}', '{"x":1e999}', '{"x":1,"x":2}'])
def test_invalid_worker_result(raw):
    r = run_json_worker(command(
        f"import sys; from pathlib import Path; Path(sys.argv[-1]).write_text({raw!r})"
    ), timeout_seconds=10)
    assert r.status == "RESULT_INVALID" and r.payload is None


def test_no_result_and_oversize():
    assert run_json_worker(command("pass"), timeout_seconds=10).status == "RESULT_MISSING_OR_OVERSIZED"
    r = run_json_worker(command(
        "import sys; from pathlib import Path; Path(sys.argv[-1]).write_text('x'*100)"
    ), timeout_seconds=10, max_bytes=16)
    assert r.status == "RESULT_MISSING_OR_OVERSIZED"


def test_atomic_writer(tmp_path):
    path = tmp_path / "result.json"
    write_worker_result(path, {"x": "中文", "v": None})
    assert json.loads(path.read_text(encoding="utf-8")) == {"x": "中文", "v": None}
    assert not path.with_suffix(".part").exists()
    with pytest.raises(ValueError):
        write_worker_result(path, {"x": float("nan")})
    with pytest.raises(ValueError):
        write_worker_result(path, {"x": "long"}, max_bytes=1)


@pytest.mark.parametrize("timeout", [0, -1, 91, float("nan"), True])
def test_invalid_limits(timeout):
    with pytest.raises(ValueError):
        run_json_worker(command("pass"), timeout_seconds=timeout)


def test_cleanup_failure_is_not_claimed_as_timeout(monkeypatch):
    class BadProcess:
        def wait(self, timeout):
            raise subprocess.TimeoutExpired("test", timeout)
        def kill(self):
            pass

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: BadProcess())
    with pytest.raises(RuntimeError, match="termination unverified"):
        run_json_worker(command("pass"), timeout_seconds=1)
