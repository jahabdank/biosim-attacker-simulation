"""Finish Astra GPT-6 T0 after technical heartbeat cut, then fresh unlabeled."""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import json
import os
from pathlib import Path
import runpy
import sys
import time

HERE = Path(__file__).resolve().parent
Z = Path(str(_archive_path('path_034')))
sys.path.insert(0, str(HERE))

# Complete all unstarted T0 jobs. Existing completed + failed cells are skipped.
sys.argv = [
    "run_resume_remaining.py",
    str(Z / "gpt6-astra-t0-triple-20260923"),
    str(Z / "gpt6-astra-t0-triple-20260923b"),
]
runpy.run_path(str(HERE / "run_resume_remaining.py"), run_name="__main__")

result = json.loads((Z / "gpt6-astra-t0-triple-20260923b" / "status.json").read_text())
if result.get("state") != "completed":
    raise SystemExit(2)

# Use the fixed phase implementation, but a fresh unlabeled directory.
from run_gpt6_t0_unlabeled import phase, save
supervisor = Z / "gpt6-astra-resume-then-unlabeled-20260923"
supervisor.mkdir(parents=True, exist_ok=True)
save(supervisor / "status.json", dict(state="running", controller_pid=os.getpid(), started=time.time(), launched=[]))
# phase() has a fixed directory name; use a date-suffixed alias by monkeypatching HOST_A is not safe.
# The premature directory is retained. Rename is avoided; implement by copying the manifest jobs into a fresh run via resume runner.
from run_gpt6_t0_unlabeled import jobs_for, execute, SPACING, UNLABELED_ID
run = Z / "gpt6-astra-unlabeled-triple-20260923b"
run.mkdir(parents=True, exist_ok=False)
items = jobs_for("gpt-6-astra", "unlabeled")
save(run / "manifest.json", dict(jobs=items, n=18, model="gpt-6-astra", phase="unlabeled", spacing_seconds=SPACING, identity=str(UNLABELED_ID), notes="Fresh unlabeled after Astra T0 resume; premature prior cell excluded."))
state = dict(state="running", model="gpt-6-astra", phase="unlabeled", completed=0, controller_pid=os.getpid(), started=time.time())
save(run / "status.json", state)
for item in items:
    result = execute(run / item["job_id"].replace(":", "__"), item)
    if result["state"] != "completed":
        if result.get("incomplete") == "route_error":
            state.setdefault("route_errors", []).append(item["job_id"])
            save(run / "status.json", state)
            continue
        state.update(state="failed", failed=item["job_id"], ended=time.time())
        save(run / "status.json", state)
        raise SystemExit(2)
    state["completed"] += 1
    save(run / "status.json", state)
state.update(state="completed", ended=time.time())
save(run / "status.json", state)
save(supervisor / "status.json", dict(state="completed", ended=time.time(), t0="completed", unlabeled="completed"))
