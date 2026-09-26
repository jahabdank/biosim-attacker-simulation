"""Migration toolkit: dry-run, fail-closed cutover, no secret leakage."""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "scripts" / "docker-migration" / "migrate.py"


def _load():
    spec = importlib.util.spec_from_file_location("satml_migrate", MOD)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_redact_env_and_dict():
    m = _load()
    assert m.redact_env("POSTGRES_PASSWORD=hunter2") == "POSTGRES_PASSWORD=<redacted>"
    assert m.redact_env("POSTGRES_USER=provider_proxy") == "POSTGRES_USER=provider_proxy"
    d = m.redact({"Env": ["POSTGRES_PASSWORD=x", "POSTGRES_DB=provider_proxy"], "Image": "postgres:16-alpine"})
    assert d["Env"][0].endswith("<redacted>")
    assert "provider_proxy" in d["Env"][1]


def test_cutover_without_apply_does_not_mutate():
    m = _load()
    out = m.phase_cutover({"phases": {}}, apply=False)
    assert out["applied"] is False
    assert out["script"].endswith("cutover.py")


def test_cutover_apply_without_root_exits(monkeypatch):
    m = _load()
    monkeypatch.setattr(m.os, "geteuid", lambda: 1000)
    with pytest.raises(SystemExit, match="root"):
        m.phase_cutover({"phases": {}}, apply=True)


def test_privileged_script_refuses_without_apply():
    import subprocess

    script = ROOT / "scripts" / "docker-migration" / "privileged-cutover.sh"
    proc = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert proc.returncode == 2
    assert "--apply" in (proc.stderr + proc.stdout)


def test_pinned_version_is_29_line():
    m = _load()
    assert "29.6.1" in m.PINNED_DOCKER_CE
    assert "noble" in m.PINNED_DOCKER_CE
