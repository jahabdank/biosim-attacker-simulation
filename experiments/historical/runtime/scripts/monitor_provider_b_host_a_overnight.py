#!/usr/bin/env python3
"""Deterministic terminal monitor for the frozen provider_b overnight extension."""

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import argparse
import json
import os
import time
from pathlib import Path

ROOT = Path(str(_archive_path('path_030')))
ADMISSION = Path(str(_archive_path('path_031')))
MODELS = ("grok-4.6-route-b", "claude-sonnet-5-route-b", "claude-opus-5-route-b")
FAIL_STATES = {"paused_failure", "paused_unreconciled", "paused_incomplete", "paused_qualification", "qualification_failed"}
HEARTBEAT_MAX_AGE_S = 1800


def pid_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def check(now: float | None = None) -> str | None:
    now = time.time() if now is None else now
    if not (ROOT / "manifest.json").is_file():
        return "FAILED"
    leases = []
    if ADMISSION.is_file():
        try:
            leases = (json.loads(ADMISSION.read_text()).get("leases") or [])
        except (OSError, json.JSONDecodeError):
            return "FAILED"
    lease_ids = {x.get("attempt_id") for x in leases if pid_alive(x.get("pid"))}
    states = {}
    attempts = []
    for model in MODELS:
        path = ROOT / "models" / model / "ledger.json"
        if not path.is_file():
            return "FAILED"
        try:
            ledger = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return "FAILED"
        states[model] = ledger.get("state")
        rows = ledger.get("attempts") or []
        attempts.extend(rows)
        for row in rows:
            if row.get("status") not in {"reserved", "running"}:
                continue
            if not pid_alive(row.get("controller_pid")):
                return "FAILED"
            if row.get("attempt_id") not in lease_ids:
                return "FAILED"
            heartbeat = row.get("heartbeat_at", row.get("started"))
            if not isinstance(heartbeat, (int, float)) or now - heartbeat > HEARTBEAT_MAX_AGE_S:
                return "FAILED"
    if any(state in FAIL_STATES or str(state).startswith("paused_") for state in states.values()):
        return "FAILED"
    if all(state == "completed" for state in states.values()):
        if len(attempts) != 36 or len({x.get("job_id") for x in attempts}) != 36 or any(x.get("status") != "ok" for x in attempts):
            return "FAILED"
        return "DONE"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true", help="Poll silently until DONE or FAILED")
    parser.add_argument("--interval", type=float, default=15.0)
    args = parser.parse_args()
    while True:
        event = check()
        if event:
            print(event, flush=True)
            return 0 if event == "DONE" else 1
        if not args.watch:
            return 2
        time.sleep(max(1.0, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
