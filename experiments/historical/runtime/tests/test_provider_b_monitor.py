
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("provider_b_monitor", Path(__file__).parents[1] / "scripts/monitor_provider_b_host_a_overnight.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def write(root, states, attempts=None):
    (root / "manifest.json").parent.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text("{}")
    for model in mod.MODELS:
        p = root / "models" / model / "ledger.json"; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"state": states[model], "attempts": (attempts or {}).get(model, [])}))


def test_monitor_running_is_silent(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "ADMISSION", tmp_path / "admission.json")
    write(tmp_path, {m: "running" for m in mod.MODELS})
    assert mod.check() is None


def test_monitor_fails_on_paused_qualification(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "ADMISSION", tmp_path / "admission.json")
    states = {m: "running" for m in mod.MODELS}; states["claude-opus-5-route-b"] = "paused_qualification"
    write(tmp_path, states)
    assert mod.check() == "FAILED"


def test_monitor_fails_on_dead_controller(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "ADMISSION", tmp_path / "admission.json")
    row = {"attempt_id": "a", "job_id": "j", "status": "running", "controller_pid": 999999999, "heartbeat_at": 100}
    write(tmp_path, {m: "running" for m in mod.MODELS}, {"grok-4.6-route-b": [row]})
    mod.ADMISSION.write_text(json.dumps({"leases": [{"attempt_id": "a", "pid": 999999999}]}))
    assert mod.check(now=101) == "FAILED"


def test_monitor_fails_on_missing_lease(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "ADMISSION", tmp_path / "admission.json")
    monkeypatch.setattr(mod, "pid_alive", lambda pid: True)
    row = {"attempt_id": "a", "job_id": "j", "status": "running", "controller_pid": 123, "heartbeat_at": 100}
    write(tmp_path, {m: "running" for m in mod.MODELS}, {"grok-4.6-route-b": [row]})
    mod.ADMISSION.write_text('{"leases": []}')
    assert mod.check(now=101) == "FAILED"


def test_monitor_fails_on_stale_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "ADMISSION", tmp_path / "admission.json")
    monkeypatch.setattr(mod, "pid_alive", lambda pid: True)
    row = {"attempt_id": "a", "job_id": "j", "status": "running", "controller_pid": 123, "heartbeat_at": 100}
    write(tmp_path, {m: "running" for m in mod.MODELS}, {"grok-4.6-route-b": [row]})
    mod.ADMISSION.write_text(json.dumps({"leases": [{"attempt_id": "a", "pid": 123}]}))
    assert mod.check(now=100 + mod.HEARTBEAT_MAX_AGE_S + 1) == "FAILED"


def test_monitor_done_requires_exact_36_unique_successes(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "ADMISSION", tmp_path / "admission.json")
    attempts = {m: [{"job_id": f"{m}-{i}", "status": "ok"} for i in range(12)] for m in mod.MODELS}
    write(tmp_path, {m: "completed" for m in mod.MODELS}, attempts)
    assert mod.check() == "DONE"
