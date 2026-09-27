"""Filesystem roots for the operator room.

``BIOSIM_RUNS_ROOT`` relocates experiment **results** off the git checkout
onto this host's writable namespace under the shared external external
tree. Hosts may **read** each other's completed results after sync; they
must not share one mutable ledger. Inputs under ``data/`` stay in-repo.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def runs_root() -> Path:
    """Directory that holds study/grid experiment artifacts.

    Override with ``BIOSIM_RUNS_ROOT`` (absolute, relative to the repo, or
    ``~``-relative). That override should be this host's namespace
    (for example ``.../biosim-runs/hosts/external``), never the shared
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
