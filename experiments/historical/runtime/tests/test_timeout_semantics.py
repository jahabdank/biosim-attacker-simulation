
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import json
import os
import subprocess
from pathlib import Path

import pytest

from biosim_operator.cli_episode import (
    is_max_turns_exit,
    recovered_watch_prompt,
    should_advance_leftover,
    timeout_partial_output,
)

ROOT = Path(__file__).resolve().parents[1]
EVA_JAR = (
    _archive_path('path_032')
)
HUNG = ROOT / "tests" / "hung_operator.py"


def test_timeout_partial_output_preserves_bytes_and_str():
    exc = subprocess.TimeoutExpired(cmd=["x"], timeout=1, output=b"PARTIAL-BYTES")
    out, err = timeout_partial_output(exc)
    assert out == "PARTIAL-BYTES"
    assert err == ""
    exc2 = subprocess.TimeoutExpired(cmd=["x"], timeout=1, output="PARTIAL-STR", stderr="e")
    out2, err2 = timeout_partial_output(exc2)
    assert out2 == "PARTIAL-STR"
    assert err2 == "e"


def test_exact_max_turn_exit_classification():
    good = subprocess.CompletedProcess(["grok"], 1, "", "Error: max turns reached\n")
    other = subprocess.CompletedProcess(["grok"], 1, "", "Error: transport closed\n")
    success = subprocess.CompletedProcess(["grok"], 0, "", "Error: max turns reached\n")
    assert is_max_turns_exit(good, good.stderr)
    assert not is_max_turns_exit(other, other.stderr)
    assert not is_max_turns_exit(success, success.stderr)
    assert not is_max_turns_exit(None, "Error: max turns reached")


def test_recovered_watch_prompt_states_boundary_and_new_clock():
    text = recovered_watch_prompt(
        2, 32.0, n_dead=0, n_crew=4, clock="2042-03-04 08:00"
    )
    assert "previous watch closed" in text.lower()
    assert "remainder of that four-hour watch" in text.lower()
    assert "new watch" in text.lower()
    assert "2042-03-04 08:00" in text
    assert "rather than continuing an unfinished inspection sequence" in text


def test_should_not_advance_leftover_on_incomplete_timeout():
    assert should_advance_leftover(leftover=240, timed_out=True, incomplete_on_timeout=True) is False
    assert should_advance_leftover(leftover=240, timed_out=True, incomplete_on_timeout=False) is True
    assert should_advance_leftover(leftover=240, timed_out=False, incomplete_on_timeout=True) is True
    assert should_advance_leftover(leftover=0, timed_out=False, incomplete_on_timeout=False) is False


def test_timeout_e2e_mocked_hung_runner_isolated_jvm(tmp_path):
    if not EVA_JAR.is_file():
        pytest.skip(f"EVA jar missing at {EVA_JAR}")
    run_id = "study-timeout-e2e"
    artifact = tmp_path / run_id
    from biosim_operator.server import BioSimServer, allocate_free_port
    server = BioSimServer(jar=EVA_JAR, host="127.0.0.1", port=allocate_free_port())
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["BIOSIM_JAR"] = str(EVA_JAR)
    env["BIOSIM_URL"] = server.base_url
    env.pop("STUDY_ROUTE_DIAGNOSTICS", None)
    env.pop("FARSIDE_DOCKER", None)
    import sys

    hung = f"{sys.executable} {HUNG}"
    argv = [
        sys.executable,
        "-m",
        "biosim_operator.cli_episode",
        "--operator",
        "mock",
        "--mock-cmd",
        hung,
        "--mode",
        "advanced",
        "--stability",
        "stable",
        "--turns",
        "2",
        "--timeout",
        "1",
        "--warmup-hours",
        "0",
        "--ticks-per-turn",
        "4",
        "--incomplete-on-timeout",
        "--run-id",
        run_id,
        "--probe",
        "none",
        "--artifact-dir",
        str(artifact),
        "--plant-url",
        server.base_url,
    ]
    try:
        server.start(reuse_existing=False)
        proc = subprocess.run(argv, cwd=str(ROOT), env=env, text=True, capture_output=True)
        assert proc.returncode == 2, (proc.stdout[-1500:], proc.stderr[-2000:])
        stdout_wake = artifact / "wakes" / "01.stdout"
        assert stdout_wake.is_file()
        assert "PARTIAL-BYTES-BEFORE-HANG" in stdout_wake.read_text()
        assert not (artifact / "wakes" / "02.json").exists()
        outcome = json.loads((artifact / "outcome.json").read_text())
        assert outcome["status"] == "incomplete"
        assert outcome["incomplete"] is True
        assert outcome["score"]["reason"] == "incomplete"
        assert outcome["score"]["reason"] != "horizon"
        ticks = (outcome.get("habitat") or {}).get("ticks") or 0
        assert ticks < 240
    finally:
        server.stop()
