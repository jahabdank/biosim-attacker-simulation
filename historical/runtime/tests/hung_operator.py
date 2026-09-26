#!/usr/bin/env python3
"""Partial stdout, then hang. Used by timeout E2E tests. No network."""

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import sys
import time

sys.stdout.write("PARTIAL-BYTES-BEFORE-HANG\n")
sys.stdout.flush()
time.sleep(3600)
