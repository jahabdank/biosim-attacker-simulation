#!/usr/bin/env python3
"""Run one full no-injection validation each for Grok and Luna; Sonnet already runs."""

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import concurrent.futures
import fcntl
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from biosim_operator.paths import runs_root
from biosim_operator.study import build_full_manifest, launch_cli_episode, episode_dir, required_artifacts, classify_attempt, collect_attempt_usage

RUN = runs_root() / "20260907-route-smokes"
MODELS = ("grok-4.6", "gpt-5.6-luna")


def write(path, data):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def execute(job):
    artifact = episode_dir(RUN, job["job_id"])
    proc = launch_cli_episode(job, run_dir=RUN)
    path = artifact / "outcome.json"
    outcome = json.loads(path.read_text()) if path.exists() else {}
    status = classify_attempt(returncode=proc.returncode, outcome=outcome, missing=required_artifacts(artifact), stderr=proc.stderr or "")
    score = outcome.get("score", {})
    return {"model":job["model"], "kind":"technical-validation", "status":status,
            "n_dead":outcome.get("n_dead",score.get("n_dead")), "n_crew":outcome.get("n_crew",score.get("n_crew")),
            "artifact":str(artifact), "usage":collect_attempt_usage(artifact), "returncode":proc.returncode}


def main():
    if os.geteuid()!=0 or not os.environ.get("ROUTE_A_HARNESS_API_KEY"):
        raise SystemExit("Requires Docker privileges and trusted-controller provider_a credential")
    RUN.mkdir(parents=True,exist_ok=True)
    with (RUN/"lock").open("a+") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state=RUN/"status.json"
        if state.exists():
            raise SystemExit("Smoke attempts already recorded; no automatic duplicates")
        jobs=[next(j for j in build_full_manifest() if j["model"]==m and j["arm"]=="control" and j["trust"]=="t1" and j["repeat"]==1) for m in MODELS]
        data={"state":"running","started":time.time(),"jobs":jobs,"results":[],"sonnet":"existing first72 control T1"}
        write(state,data)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            pending={pool.submit(execute,j):j for j in jobs}
            for future in concurrent.futures.as_completed(pending):
                job=pending[future]
                try: result=future.result()
                except Exception as exc: result={"model":job["model"],"status":"failed","error":str(exc)[:1000]}
                data["results"].append(result)
                if result["status"]!="ok" or result.get("n_dead")!=0 or result.get("n_crew")!=4:
                    data["state"]="failed"
                write(state,data)
                print(json.dumps(result),flush=True)
        if data["state"]!="failed":data["state"]="completed"
        write(state,data)
        return 0 if data["state"]=="completed" else 2


if __name__=="__main__":
    raise SystemExit(main())
