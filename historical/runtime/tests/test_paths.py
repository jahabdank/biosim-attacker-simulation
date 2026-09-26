"""BIOSIM_RUNS_ROOT override and controller imports."""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import ast
import importlib.util
import sys
from pathlib import Path

from biosim_operator import paths
from biosim_operator.study import HARNESS_FILES, ROOT


def test_default_runs_root_is_repo_runs(monkeypatch):
    monkeypatch.delenv("BIOSIM_RUNS_ROOT", raising=False)
    assert paths.runs_root() == (ROOT / "runs").resolve()


def test_absolute_override(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BIOSIM_RUNS_ROOT", str(tmp_path))
    assert paths.runs_root() == tmp_path.resolve()


def test_relative_override(monkeypatch):
    monkeypatch.setenv("BIOSIM_RUNS_ROOT", "rel-namespace")
    assert paths.runs_root() == (ROOT / "rel-namespace").resolve()


def test_tilde_override(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("BIOSIM_RUNS_ROOT", "~/host-ns")
    assert paths.runs_root() == (tmp_path / "host-ns").resolve()


def test_paths_py_is_in_harness_fingerprint_set():
    assert "src/biosim_operator/paths.py" in HARNESS_FILES
    assert (ROOT / "src/biosim_operator/paths.py").is_file()


def _load(rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_run_next_batch_imports_runs_root():
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "scripts/study"))
    module = _load("scripts/study/run_next_batch.py")
    assert module.DEFAULT == paths.runs_root() / "20260907-next46"


def test_run_route_smokes_imports_runs_root():
    sys.path.insert(0, str(ROOT / "src"))
    module = _load("scripts/study/run_route_smokes.py")
    assert module.RUN == paths.runs_root() / "20260907-route-smokes"


def test_entrypoint_modules_compile():
    files = [
        "src/biosim_operator/paths.py",
        "src/biosim_operator/study.py",
        "src/biosim_operator/cli_episode.py",
        "scripts/study/run_next_batch.py",
        "scripts/study/run_route_smokes.py",
        "scripts/study/run_first_batch.py",
        "scripts/study/run_next_recovery.py",
        "scripts/study/validate_native_subscription.py",
        "scripts/study/verify_container_runtime.py",
    ]
    for rel in files:
        source = (ROOT / rel).read_text()
        ast.parse(source)
        compile(source, rel, "exec")
