"""Finish provider_a Grok T1 remainder, then T0. Do not retry 502 cells."""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import os
from pathlib import Path
import runpy
import sys

HERE = Path(__file__).resolve().parent
Z = Path(str(_archive_path('path_034')))

sys.path.insert(0, str(HERE))
from run_t0_followon import LANES, lane, save
import json, time

# T1 remainder
sys.argv = [
    "run_resume_remaining.py",
    str(Z / "route_a-grok-triple-20260919c"),
    str(Z / "route_a-grok-triple-20260919e"),
    str(Z / "route_a-grok-triple-20260919d"),
]
runpy.run_path(str(HERE / "run_resume_remaining.py"), run_name="__main__")

# T0 after remainder (fresh dir; aborted 90s T0 cell is not science)
cfg = dict(
    LANES["grok-4.6-route-a"],
    gate=None,
    run_name="route_a-grok-t0-triple-20260920",
    study_id="route_a-grok-t0-triple-20260920",
)
supervisor = Z / "route_a-t1-then-t0-20260920"
supervisor.mkdir(parents=True, exist_ok=True)
save(supervisor / "status.json", dict(state="running", controller_pid=os.getpid(), started=time.time(), launched=["t1-remainder"]))
lane(supervisor, "grok-4.6-route-a", cfg)
d = json.loads((supervisor / "status.json").read_text())
d.update(state="completed", ended=time.time())
save(supervisor / "status.json", d)
