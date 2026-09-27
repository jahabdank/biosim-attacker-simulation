#!/usr/bin/env python3
"""Far-side outpost ECLSS panel. stdio. Seating is this console."""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import json
import os
import runpy
import sys
from pathlib import Path


def _station() -> Path:
    override = os.environ.get("FARSIDE_HOME", "").strip()
    if override:
        return Path(override)
    return Path("/opt/farside")


def _watch_id(argv: list[str]) -> str:
    marker = Path.cwd() / ".console"
    if marker.is_file():
        for line in marker.read_text().splitlines():
            if line.startswith("id="):
                return line.split("=", 1)[1].strip()
    if "--watch" in argv:
        index = argv.index("--watch")
        if index + 1 < len(argv):
            return argv[index + 1]
    return Path.cwd().name


def main() -> None:
    watch = _watch_id(sys.argv)
    station = _station()
    var = station / "var" / watch
    cfg = json.loads((var / "launch.json").read_text())
    os.environ["ECLSS_URL"] = str(cfg["url"])
    os.environ["ECLSS_MODE"] = str(cfg["mode"])
    os.environ["ECLSS_STATE"] = str(var / "state")
    os.environ["ECLSS_TRANSCRIPT"] = str(var / "console.log")
    lib = station / "lib"
    existing = os.environ.get("PYTHONPATH", "")
    if lib.is_dir():
        os.environ["PYTHONPATH"] = str(lib) + (os.pathsep + existing if existing else "")
        if str(lib) not in sys.path:
            sys.path.insert(0, str(lib))
    sys.argv = [sys.argv[0]]
    for mcp in sorted(lib.glob("*/mcp_server.py")) if lib.is_dir() else []:
        runpy.run_module(mcp.parent.name + ".mcp_server", run_name="__main__")
        return
    raise FileNotFoundError(f"no panel under {lib}")


if __name__ == "__main__":
    main()
