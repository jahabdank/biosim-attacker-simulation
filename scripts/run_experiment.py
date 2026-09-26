#!/usr/bin/env python3
"""Launch a frozen matrix through the original CLI episode loop; offline by default."""
from __future__ import annotations
import argparse
import concurrent.futures
import fcntl
import json
import os
import signal
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from biosim_operator.manifest import load_manifest, resolve_job
from biosim_operator.provider_config import load_provider
from biosim_operator.study import launch_cli_episode, episode_dir, cancel_active


def write(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "manifests/offline-control.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--container", action="store_true", help="Container qualification with fake CLI; live always uses containers")
    parser.add_argument("--limit", type=int, help="Subset for technical qualification; records are not a complete matrix")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    data = load_manifest(args.manifest)
    jobs = data["jobs"]
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be positive")
        jobs = jobs[:args.limit]
    if args.validate:
        print(json.dumps({"valid": True, "jobs": len(jobs), "manifest": args.manifest.name}))
        return 0
    if not args.output:
        parser.error("--output is required; use a new directory outside the repository")
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        parser.error("output must be outside the repository")
    if args.allow_live:
        for job in jobs:
            provider = load_provider(job["model"])
            if provider["kind"] != job["route"]:
                parser.error("provider kind differs from manifest route")
            for field in ("context_window", "max_completion_tokens"):
                if provider[field] != job[field]:
                    parser.error(f"provider {field} differs from manifest")
            if job["route"] == "api" and provider["api_backend"] != job["api_backend"]:
                parser.error("provider API backend differs from manifest")
    output.mkdir(parents=True, exist_ok=False)
    write(output / "manifest.json", {**data, "jobs": jobs, "offline": not args.allow_live,
                                    "qualification_subset": args.limit is not None})
    lock_dir = Path(os.environ.get("BIOSIM_LOCK_DIR", "/tmp/eclss-locks"))
    lock_dir.mkdir(parents=True, exist_ok=True)
    lanes = {}
    for index, job in enumerate(jobs):
        lanes.setdefault(job["model"], []).append((index, job))
    ledger_lock = threading.Lock()
    stop = threading.Event()
    def interrupted(signum, frame):
        stop.set()
        cancel_active()
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)

    def execute(item):
        index, job = item
        folder = output / f"{index + 1:04d}"
        folder.mkdir()
        env = dict(os.environ)
        if args.allow_live:
            env["BIOSIM_ALLOW_LIVE"] = "1"
            env.pop("STUDY_FAKE_GROK", None)
        else:
            env.pop("BIOSIM_ALLOW_LIVE", None)
            env["STUDY_FAKE_GROK"] = str(ROOT / "scripts/fake_grok.py")
        state = {"job_id": job["job_id"], "state": "running", "offline": not args.allow_live}
        write(folder / "status.json", state)
        try:
            proc = launch_cli_episode(resolve_job(job), run_dir=folder, env=env,
                                      container_grok=args.container or args.allow_live)
            file = episode_dir(folder, job["job_id"]) / "outcome.json"
            outcome = json.loads(file.read_text()) if file.exists() else {}
            state.update(state="completed" if proc.returncode == 0 and outcome and not outcome.get("incomplete") else "failed",
                         returncode=proc.returncode, n_dead=outcome.get("n_dead"),
                         incomplete_reason=outcome.get("incomplete_reason"),
                         watch_cap_recoveries=outcome.get("watch_cap_recoveries", []))
        except Exception as exc:
            state.update(state="failed", error_class=type(exc).__name__)
        write(folder / "status.json", state)
        with ledger_lock, (output / "attempts.jsonl").open("a") as stream:
            stream.write(json.dumps(state) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return state

    def lane(model, items):
        with (lock_dir / (model + ".lock")).open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            results = []
            concurrency = int(data.get("per_model_concurrency", 1))
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                for start in range(0, len(items), concurrency):
                    if stop.is_set():
                        break
                    block = list(pool.map(execute, items[start:start + concurrency]))
                    results.extend(block)
                    hard_failure = any(r["state"] != "completed" and not (
                        data.get("continue_route_errors", False) and r.get("incomplete_reason") == "route_error") for r in block)
                    if hard_failure:
                        break
            return results

    results = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=int(data.get("model_concurrency", 1))) as pool:
            futures = [pool.submit(lane, model, items) for model, items in lanes.items()]
            try:
                for future in concurrent.futures.as_completed(futures):
                    results.extend(future.result())
            except BaseException:
                stop.set()
                cancel_active()
                raise
    except BaseException:
        stop.set()
        cancel_active()
        write(output / "status.json", {"state": "interrupted", "attempted": len(results), "assigned": len(jobs)})
        raise
    ok = len(results) == len(jobs) and all(r["state"] == "completed" for r in results)
    write(output / "status.json", {"state": "interrupted" if stop.is_set() else ("completed" if ok else "partial_failure"),
                                  "assigned": len(jobs), "attempted": len(results), "offline": not args.allow_live})
    print(json.dumps({"state": "completed" if ok else "partial_failure", "attempted": len(results), "assigned": len(jobs)}))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
