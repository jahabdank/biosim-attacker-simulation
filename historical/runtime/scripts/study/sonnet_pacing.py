"""Admission pacing for a single Sonnet episode; no retries or model substitution."""

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import fcntl
import json
import math
import os
import time
from pathlib import Path


def validate_spacing(value: float | str) -> float:
    spacing = float(value)
    if not math.isfinite(spacing) or spacing <= 0:
        raise ValueError("Sonnet spacing must be finite and positive")
    return spacing


def reserve_start(state_path: Path, minimum_spacing_s: float = 65.0) -> float:
    minimum_spacing_s = validate_spacing(minimum_spacing_s)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.with_suffix('.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous=json.loads(state_path.read_text()).get('last_start',0) if state_path.exists() else 0
        wait=max(0,previous+minimum_spacing_s-time.time())
        if wait:
            time.sleep(wait)
        started=time.time()
        temp=state_path.with_suffix('.tmp')
        with temp.open('w') as f:
            json.dump({'last_start':started},f)
            f.flush();os.fsync(f.fileno())
        os.replace(temp,state_path)
        return wait
