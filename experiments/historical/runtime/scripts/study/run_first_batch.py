#!/usr/bin/env python3
"""Frozen 72-episode first batch with bounded per-model concurrency."""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


from biosim_operator.paths import runs_root

import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from biosim_operator.study import build_full_manifest, collect_fingerprints, flatten_fingerprints, launch_cli_episode, collect_attempt_usage, classify_attempt, required_artifacts, episode_dir

CAPS = {"grok-4.6": 4, "gpt-5.6-luna": 3, "claude-sonnet-5": 1}
DEFAULT = runs_root() / "20260907-first72-container-v3"


def save(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def select_jobs() -> list[dict]:
    selected = []
    for job in build_full_manifest():
        arm, repeat = job["arm"], job["repeat"]
        if ((arm == "attack" and repeat <= 2)
            or (arm == "control" and repeat == 1)
            or (arm == "envelope" and repeat == 1)
            or (arm == "benign" and job["trust"] == "t2" and repeat == 1)):
            selected.append(job)
    assert len(selected) == 72
    random.Random(20260907).shuffle(selected)
    # Establish each model's normal operation before its attack jobs.
    return sorted(selected, key=lambda j: j["arm"] != "control")


def verify(manifest: dict) -> None:
    current = flatten_fingerprints(collect_fingerprints())
    frozen = flatten_fingerprints(manifest["fingerprints"])
    ignored = {"wrapper_git.status_sha256", "wrapper_git.dirty", "wrapper_git.error"}
    changed = [k for k in frozen.keys() | current.keys() if k not in ignored and current.get(k) != frozen.get(k)]
    for rel, digest in manifest["batch_files"].items():
        if hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() != digest:
            changed.append(rel)
    if changed:
        raise RuntimeError("Frozen runtime changed: " + ", ".join(changed[:8]))


def execute(job: dict, run_dir: Path) -> dict:
    start = time.time()
    artifact = episode_dir(run_dir, job["job_id"])
    try:
        proc = launch_cli_episode(job, run_dir=run_dir)
        outcome = json.loads((artifact / "outcome.json").read_text()) if (artifact / "outcome.json").exists() else {}
        missing = required_artifacts(artifact)
        status = classify_attempt(returncode=proc.returncode, outcome=outcome, missing=missing, stderr=proc.stderr or "")
        usage = collect_attempt_usage(artifact)
        score = outcome.get("score", {})
        return {"status": status, "returncode": proc.returncode, "elapsed_s": time.time()-start,
                "n_dead": outcome.get("n_dead", score.get("n_dead")), "n_crew": outcome.get("n_crew", score.get("n_crew")),
                "usage": usage, "artifact": str(artifact), "missing": missing}
    except Exception as exc:
        return {"status": "failed", "elapsed_s": time.time()-start, "error": str(exc)[:1000], "artifact": str(artifact)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--run-dir", type=Path, default=DEFAULT)
    parser.add_argument("--models", nargs="+", choices=tuple(CAPS), default=list(CAPS))
    args = parser.parse_args()
    args.run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.run_dir / "manifest.json"
    if args.freeze:
        if manifest_path.exists():
            raise SystemExit("Existing manifest will not be overwritten")
        files = ["scripts/study/run_first_batch.py", "scripts/study/route_broker.py", "scripts/study/connect_proxy.py", "scripts/study/sonnet_pacing.py"]
        selected = [j for j in select_jobs() if j["model"] in args.models]
        data = {"jobs": selected, "caps": {m:CAPS[m] for m in args.models}, "fingerprints": collect_fingerprints(),
                "batch_files": {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files},
                "approved_max_attempts":len(selected),"created":time.time(),"full_study":264}
        save(manifest_path,data)
        print(json.dumps({"frozen":str(manifest_path),"n":len(data["jobs"]),"models":dict(Counter(j["model"] for j in data["jobs"]))}))
        return 0
    manifest=json.loads(manifest_path.read_text())
    verify(manifest)
    if not args.run:
        print(json.dumps({"verified":True,"n":len(manifest["jobs"]),"caps":CAPS}))
        return 0
    if os.geteuid()!=0:
        raise SystemExit("Run with sudo for contained Docker execution")
    if not os.environ.get("ROUTE_A_HARNESS_API_KEY"):
        raise SystemExit("provider_a key missing from trusted controller")
    ledger_path=args.run_dir/"attempts.json"
    with (args.run_dir/"runner.lock").open("a+") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else {"attempts":[],"cap":manifest["approved_max_attempts"],"state":"running"}
        if any(a["status"]=="running" for a in ledger["attempts"]):
            raise SystemExit("Interrupted attempts require reconciliation; no automatic retry")
        tried={a["job_id"] for a in ledger["attempts"]}
        pending=[j for j in manifest["jobs"] if j["job_id"] not in tried]
        running={};pause=False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            while pending or running:
                counts=Counter(j["model"] for j,_ in running.values())
                control_phase = any(j["arm"] == "control" for j in pending) or any(j["arm"] == "control" for j,_ in running.values())
                for active_job,_ in running.values():
                    for wake in (episode_dir(args.run_dir,active_job["job_id"])/"wakes").glob("*.json"):
                        w=json.loads(wake.read_text())
                        if w.get("timed_out") or w.get("returncode") not in (0,None):
                            pause=True;ledger["state"]="paused_technical_failure";save(ledger_path,ledger)
                if (args.run_dir/"PAUSE-AFTER-CURRENT").exists():
                    pause=True;ledger["state"]="paused_operator_request";save(ledger_path,ledger)
                if not pause:
                    for job in list(pending):
                        if control_phase and job["arm"] != "control":continue
                        if counts[job["model"]]>=CAPS[job["model"]] or len(running)>=8:continue
                        if len(ledger["attempts"])>=manifest["approved_max_attempts"]:break
                        verify(manifest)
                        pending.remove(job)
                        row={"job_id":job["job_id"],"model":job["model"],"arm":job["arm"],"trust":job["trust"],"status":"running","started":time.time()}
                        ledger["attempts"].append(row);save(ledger_path,ledger)
                        future=pool.submit(execute,job,args.run_dir);running[future]=(job,row);counts[job["model"]]+=1
                        print("START",job["job_id"],flush=True)
                if not running:break
                done,_=concurrent.futures.wait(running,timeout=10,return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    job,row=running.pop(future);row.update(future.result());save(ledger_path,ledger)
                    print("END",job["job_id"],row["status"],"dead",row.get("n_dead"),flush=True)
                    if row["status"]!="ok" or row.get("n_crew")!=4:
                        pause=True;ledger["state"]="paused_technical_failure";save(ledger_path,ledger)
                    if job["arm"]=="control" and row.get("n_dead",0):
                        pause=True;ledger["state"]="paused_control_failure";save(ledger_path,ledger)
            ledger["state"]="paused_technical_failure" if pause else "completed"
            save(ledger_path,ledger)
        print(json.dumps({"state":ledger["state"],"attempts":len(ledger["attempts"]),"remaining":len(pending)}),flush=True)
        return 2 if pause else 0


if __name__=="__main__":
    raise SystemExit(main())
