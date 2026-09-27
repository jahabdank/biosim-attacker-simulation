"""Filesystem roots for the operator room.

``BIOSIM_RUNS_ROOT`` relocates experiment **results** off the git checkout
onto this host's writable namespace under the shared controller sync_service
tree. Hosts may **read** each other's completed results after sync; they
must not share one mutable ledger. Inputs under ``data/`` stay in-repo.
"""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def runs_root() -> Path:
    """Directory that holds study/grid experiment artifacts.

    Override with ``BIOSIM_RUNS_ROOT`` (absolute, relative to the repo, or
    ``~``-relative). That override should be this host's namespace
    (for example ``.../biosim-runs/hosts/host_a``), never the shared
    historical root. Default: ``<repo>/runs`` (compatibility symlink to
    the same host namespace).
    """
    override = (os.environ.get("BIOSIM_RUNS_ROOT") or "").strip()
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            path = (ROOT / path).resolve()
        else:
            path = path.resolve()
        return path
    return (ROOT / "runs").resolve()
