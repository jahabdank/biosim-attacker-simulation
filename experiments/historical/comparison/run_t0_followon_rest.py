"""ROUTE_A + Sonnet T0 after the original follow-on process died. Wait for T1 remainders."""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import concurrent.futures
import fcntl
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_t0_followon import LANES, HOST_A, lane, save

REST = {
    "grok-4.6-route-a": dict(
        LANES["grok-4.6-route-a"],
        gate=HOST_A / "route_a-grok-triple-20260919d" / "status.json",
    ),
    "claude-sonnet-5": LANES["claude-sonnet-5"],
}


def main():
    run = Path(sys.argv[1])
    lock = Path("/run/lock/biosim-t0-followon-rest.lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    run.mkdir(parents=True, exist_ok=True)
    save(
        run / "status.json",
        dict(state="running", controller_pid=os.getpid(), started=time.time(), launched=[], waiting_on=None),
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result() for f in [pool.submit(lane, run, m, cfg) for m, cfg in REST.items()]]
    save(
        run / "status.json",
        dict(
            state="completed" if all(x.get("state") == "completed" for x in results) else "partial_failure",
            ended=time.time(),
            lanes=results,
            launched=[x["model"] for x in results],
        ),
    )


if __name__ == "__main__":
    main()
