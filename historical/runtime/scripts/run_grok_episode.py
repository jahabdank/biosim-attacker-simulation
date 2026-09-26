#!/usr/bin/env python3
"""Host Grok Build operator. Watchstander system-prompt-override."""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from biosim_operator.cli_episode import main

if __name__ == "__main__":
    raise SystemExit(main(default_operator="grok", default_model="grok-4.6"))
