#!/usr/bin/env python3
"""Explicit next46 recovery; freezing and verification do not invoke inference."""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import argparse
import concurrent.futures
import contextlib
import fcntl
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_next_batch as base

CAPS = base.CAPS
SONNET, LUNA, GROK = base.SONNET, base.LUNA, base.GROK
NEW_FILES = ["scripts/study/run_next_recovery.py", "scripts/study/recovery_diagnostics.py"]


def save(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextlib.contextmanager
def predecessor_locks(predecessor):
    # Read-only descriptors avoid changing historical lock metadata.
    with contextlib.ExitStack() as stack:
        for path in [predecessor / "runner.lock", *[predecessor / m / "model.lock" for m in CAPS]]:
            lock = stack.enter_context(path.open("r"))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def tree_hashes(directory):
    return {str(p.resolve()): base.digest(p) for p in sorted(directory.rglob("*")) if p.is_file()}


def validate_success(job, row):
    if row.get("returncode") != 0 or row.get("model") != job["model"]:
        raise RuntimeError("Successful row identity or exit code invalid")
    artifact = Path(row["artifact"])
    result = base.inspect_artifacts(job, artifact, row["returncode"])
    if result["status"] != "ok" or result.get("validation_errors"):
        raise RuntimeError("Successful artifact independently rejected")
    from recovery_diagnostics import failure_reason
    diagnostics = Path(row.get("attempt_root", artifact.parent.parent)) / "route-diagnostics.jsonl"
    if row.get("attempt_root") and job["model"] in {LUNA, SONNET} and not diagnostics.is_file():
        raise RuntimeError("Successful routed artifact lacks diagnostics")
    if diagnostics.exists() and failure_reason(diagnostics, active=False):
        raise RuntimeError("Successful artifact has route failure")
    return tree_hashes(artifact)


def prepare_plan(predecessor, ledgers):
    root = base.read_json(predecessor / "manifest.json")
    original = base.select_jobs()
    selected = {j["job_id"]: j for j in original}
    if len(ledgers) != 3 or {p.resolve() for p in ledgers} != {(predecessor / m / "attempts.json").resolve() for m in CAPS}:
        raise RuntimeError("Supply all three explicit predecessor model ledgers")
    retained = {}
    for path in ledgers:
        ledger = base.read_json(path)
        if any(row["status"] == "running" for row in ledger["attempts"]):
            raise RuntimeError("Predecessor has running rows")
    for rel, sha in root["archive"].items():
        path = predecessor / "frozen-inputs" / rel
        if base.digest(path) != sha:
            raise RuntimeError("Original frozen archive changed")
        retained[str(path.resolve())] = sha
    prior_paths = [Path(p) for p in root["prior_ledgers"]]
    for path in prior_paths:
        if base.digest(path) != root["prior_ledgers"][str(path)]:
            raise RuntimeError("Historical prior ledger changed")
    prior_ids = base.completed_ids(prior_paths)
    all_jobs = {j["job_id"]: j for j in base.study.build_full_manifest()}
    for path in prior_paths:
        for row in base.read_json(path)["attempts"]:
            if row["status"] == "ok":
                retained.update(validate_success(all_jobs[row["job_id"]], row))
    grok_controls = {j["job_id"] for j in base.study.build_full_manifest()
                     if j["model"] == GROK and j["arm"] == "control" and j["repeat"] == 1}
    if not grok_controls <= prior_ids or prior_ids & selected.keys():
        raise RuntimeError("Prior Grok controls absent or allocation overlaps")
    history, successes, failed, attempt_ids = [], {}, {}, set()
    for path in ledgers:
        model = path.parent.name
        manifest_path = path.parent / "manifest.json"
        if base.digest(manifest_path) != root["models"][model]:
            raise RuntimeError("Original model manifest changed")
        model_manifest = base.read_json(manifest_path)
        if model_manifest["jobs"] != [j for j in original if j["model"] == model]:
            raise RuntimeError("Original46 selection changed")
        ledger = base.read_json(path)
        if not (ledger["state"].startswith("paused") or ledger["state"] == "completed"):
            raise RuntimeError("Predecessor must be drained and paused or completed")
        for row in ledger["attempts"]:
            if row["status"] == "running":
                raise RuntimeError("Predecessor has running rows")
            job = selected.get(row["job_id"])
            if not job or job["model"] != model or row.get("model") != model:
                raise RuntimeError("Predecessor identity outside selection")
            if row["attempt_id"] in attempt_ids:
                raise RuntimeError("Duplicate historical attempt ID")
            attempt_ids.add(row["attempt_id"])
            history.append(row)
            if row["status"] == "ok":
                if row["job_id"] in successes:
                    raise RuntimeError("Duplicate successful scientific ID")
                retained.update(validate_success(job, row))
                successes[row["job_id"]] = row["attempt_id"]
            else:
                if job["arm"] != "control" or model not in {LUNA, SONNET} or row.get("replacement_of") or row["job_id"] in failed:
                    raise RuntimeError("Failure outside four-control authorization")
                failed[row["job_id"]] = row["attempt_id"]
            retained.update(tree_hashes(Path(row["attempt_root"])))
        retained[str(path.resolve())] = base.digest(path)
        retained[str(manifest_path.resolve())] = base.digest(manifest_path)
    if len(failed) != 4 or any(cell in successes for cell in failed):
        raise RuntimeError("Expected exactly four failed inference controls")
    setup_paths = [predecessor / "setup-launch-amendment.json", *[predecessor / m / "setup-failures-python-executable.json" for m in CAPS]]
    for path in [predecessor / "manifest.json", *prior_paths, *setup_paths]:
        retained[str(path.resolve())] = base.digest(path)
    if len(history) > 46 or len({r["job_id"] for r in history}) != len(history):
        raise RuntimeError("Historical attempt cap or duplicate admission")
    models = {}
    for model in CAPS:
        jobs = [j for j in original if j["model"] == model and j["job_id"] not in successes]
        controls = sorted(j["job_id"] for j in jobs if j["arm"] == "control")
        models[model] = {"model": model, "jobs": jobs, "concurrency": CAPS[model],
                         "gate": controls[0] if model != GROK else None,
                         "timeout_s": 900 if model == SONNET else 480,
                         "minimum_spacing_s": 20 if model == SONNET else None,
                         "quota_window_s": 60, "max_attempts": len(jobs) + int(model == SONNET),
                         "technical_replacements": {k: v for k, v in failed.items() if selected[k]["model"] == model}}
    return {"original_jobs": original, "models": models, "successful_exclusions": successes,
            "predecessor": str(predecessor), "predecessor_ledgers": [str(p.resolve()) for p in ledgers],
            "retained_files": retained, "historical_attempts": history,
            "setup_failures": {str(p): base.read_json(p) for p in setup_paths},
            "amendment": {"reason": "User authorized replacement of four failed inference controls after runtime repair",
                          "failed_attempts": failed, "usage_policy": "Retain actual and unknown usage; not zero-inference exclusions",
                          "scientific_cells": 46, "inference_attempt_cap_including_predecessor": 51,
                          "separate_empty_setup_failures": 8, "sonnet_quota_replacements": 1}}


def freeze(directory, predecessor, ledgers, confirmed):
    if not confirmed:
        raise RuntimeError("Parent drain confirmation is required")
    if directory.exists():
        raise RuntimeError("Recovery freeze requires a fresh directory")
    with predecessor_locks(predecessor):
        plan = prepare_plan(predecessor, ledgers)
        fingerprints = base.study.collect_fingerprints()
        images = fingerprints.get("docker_images", {})
        if not images.get("available") or not images.get("images") or not all(v.get("present") for v in images["images"].values()):
            raise RuntimeError("Docker image fingerprints unavailable")
        directory.mkdir(parents=True)
        archive = base.archive_inputs(directory / "frozen-inputs")
        for rel in NEW_FILES:
            target = directory / "frozen-inputs" / rel
            shutil.copy2(base.ROOT / rel, target)
            archive[rel] = base.digest(target)
        plan.update(archive=archive, fingerprints=fingerprints,
                    batch_files={rel: base.digest(base.ROOT / rel) for rel in base.FILES + NEW_FILES}, created=time.time())
        for model in CAPS:
            (directory / model).mkdir()
        save(directory / "repair-manifest.json", plan)


def verify(directory):
    plan = base.read_json(directory / "repair-manifest.json")
    for path, sha in plan["retained_files"].items():
        if base.digest(Path(path)) != sha:
            raise RuntimeError("Retained historical evidence changed")
    rebuilt = prepare_plan(Path(plan["predecessor"]), [Path(p) for p in plan["predecessor_ledgers"]])
    for key, value in rebuilt.items():
        if plan[key] != value:
            raise RuntimeError("Recovery allocation or amendment changed")
    for rel, sha in plan["archive"].items():
        if base.digest(directory / "frozen-inputs" / rel) != sha:
            raise RuntimeError("Recovery frozen archive changed")
    base.verify_runtime(plan)
    return plan


def check_ledger(manifest, ledger, allow_running=False):
    rows = ledger["attempts"]
    jobs = {j["job_id"] for j in manifest["jobs"]}
    if len(rows) > manifest["max_attempts"] or len({r["attempt_id"] for r in rows}) != len(rows):
        raise RuntimeError("Recovery attempt cap or ID violation")
    seen, quota = {}, []
    for row in rows:
        cell = row["job_id"]
        if cell not in jobs or row["model"] != manifest["model"]:
            raise RuntimeError("Recovery cell outside allocation")
        if row.get("quota_replacement"):
            amendment = ledger.get("quota_amendment", {})
            previous = seen.get(cell)
            if manifest["model"] != SONNET or not previous or not previous.get("quota_failure") or previous["status"] == "ok" or row["replacement_of"] != previous["attempt_id"] or amendment.get("failed_attempt_id") != previous["attempt_id"] or row["minimum_spacing_s"] != 65:
                raise RuntimeError("Quota replacement lineage violation")
            quota.append(row)
        elif cell in seen or row.get("replacement_of") != manifest["technical_replacements"].get(cell):
            raise RuntimeError("Duplicate recovery or technical lineage violation")
        seen[cell] = row
        if row["status"] == "running" and not allow_running:
            raise RuntimeError("Interrupted child requires explicit reconciliation; no retry")
    if len(quota) > 1:
        raise RuntimeError("Only one Sonnet quota replacement allowed")


def admit(manifest, ledger, directory, job, quota=False):
    row = {"attempt_id": uuid.uuid4().hex, "job_id": job["job_id"], "model": job["model"],
           "arm": job["arm"], "trust": job["trust"], "status": "running", "started": time.time(),
           "minimum_spacing_s": 65 if ledger.get("quota_amendment") else manifest["minimum_spacing_s"],
           "timeout_s": manifest["timeout_s"], "quota_replacement": quota,
           "replacement_of": ledger["quota_amendment"]["failed_attempt_id"] if quota else manifest["technical_replacements"].get(job["job_id"])}
    if quota and time.time() < ledger["quota_amendment"]["not_before"]:
        raise RuntimeError("Quota cooldown not elapsed")
    row["attempt_root"] = str(directory / "attempts" / row["attempt_id"])
    candidate = dict(ledger, attempts=ledger["attempts"] + [row])
    check_ledger(manifest, candidate, allow_running=True)
    Path(row["attempt_root"]).mkdir(parents=True)
    ledger["attempts"].append(row)
    save(directory / "attempts.json", ledger)
    return row


def runnable(manifest, ledger):
    rows = ledger["attempts"]
    passed = {r["job_id"] for r in rows if r["status"] == "ok"}
    tried = {r["job_id"] for r in rows}
    pending = [j for j in manifest["jobs"] if j["job_id"] not in tried]
    amendment = ledger.get("quota_amendment")
    if amendment and not any(r.get("quota_replacement") for r in rows):
        if time.time() < amendment["not_before"]:
            return [], 1
        pending.insert(0, next(j for j in manifest["jobs"] if j["job_id"] == amendment["job_id"]))
    gate = manifest["gate"]
    if gate and gate not in passed:
        return [j for j in pending if j["job_id"] == gate], 1
    controls = {j["job_id"] for j in manifest["jobs"] if j["arm"] == "control"}
    if not controls <= passed:
        pending = [j for j in pending if j["arm"] == "control"]
    return pending, manifest["concurrency"]


def execute(job, manifest, row):
    result = base.execute(job, manifest, row)
    artifact = base.study.episode_dir(Path(row["attempt_root"]), job["job_id"])
    try:
        result["usage"] = base.study.collect_attempt_usage(artifact)
    except Exception as exc:
        result["usage"] = {"usage_is_incomplete": True, "error_type": type(exc).__name__}
    if result["status"] == "ok":
        validate_success(job, dict(row, **result))
    return result


def run_model(manifest, directory, verify_callback=lambda: None):
    from recovery_diagnostics import failure_reason
    with base.exclusive(directory / "model.lock"):
        path = directory / "attempts.json"
        ledger = base.read_json(path) if path.exists() else {"state": "ready", "attempts": []}
        check_ledger(manifest, ledger)
        for retained, sha in ledger.get("quota_amendment", {}).get("retained_files", {}).items():
            if base.digest(Path(retained)) != sha:
                raise RuntimeError("Retained quota failure artifacts changed")
        for row in ledger["attempts"]:
            if row["status"] == "ok":
                validate_success(next(j for j in manifest["jobs"] if j["job_id"] == row["job_id"]), row)
        if ledger["state"].startswith("paused") or ledger["state"] == "completed":
            return ledger
        ledger["state"] = "running"
        running = {}
        def pause(reason):
            state = "paused_" + reason
            if ledger["state"] != state:
                ledger["state"] = state
                save(path, ledger)
                print("FAILED", manifest["model"], state, flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=manifest["concurrency"]) as pool:
            while True:
                if (directory / "PAUSE-AFTER-CURRENT").exists() or (directory.parent / "PAUSE-AFTER-CURRENT").exists():
                    pause("operator_request")
                for future, row in list(running.items()):
                    root = Path(row["attempt_root"])
                    reason = failure_reason(root / "route-diagnostics.jsonl", active=not future.done())
                    if reason:
                        pause(reason)
                    for wake in sorted(base.study.episode_dir(root, row["job_id"]).glob("wakes/*.json")):
                        try:
                            data = base.read_active_json(wake) if not future.done() else base.read_json(wake)
                            if data is not None and (data.get("timed_out") or data.get("returncode") != 0):
                                pause("watch_failure")
                        except (OSError, ValueError, TypeError, AttributeError):
                            pause("watch_parse_failure")
                    if future.done():
                        running.pop(future)
                        try:
                            row.update(future.result())
                        except Exception as exc:
                            row.update(status="failed", error_type=type(exc).__name__, ended=time.time(),
                                       usage={"usage_is_incomplete": True})
                        if row["status"] != "ok":
                            pause("quota" if row.get("quota_failure") else "technical_failure")
                        save(path, ledger)
                pending, cap = runnable(manifest, ledger)
                if ledger["state"] == "running":
                    for job in pending[:max(0, cap - len(running))]:
                        try:
                            verify_callback()
                            quota = bool(ledger.get("quota_amendment") and job["job_id"] == ledger["quota_amendment"]["job_id"])
                            row = admit(manifest, ledger, directory, job, quota)
                            running[pool.submit(execute, job, manifest, row)] = row
                        except Exception as exc:
                            ledger["controller_error_type"] = type(exc).__name__
                            pause("controller_error")
                            break
                if not running:
                    break
                concurrent.futures.wait(running, timeout=0.25, return_when=concurrent.futures.FIRST_COMPLETED)
        if ledger["state"].startswith("paused") and any(r.get("quota_failure") for r in ledger["attempts"] if r["status"] != "ok"):
            ledger["state"] = "paused_quota"
        passed = {r["job_id"] for r in ledger["attempts"] if r["status"] == "ok"}
        if ledger["state"] == "running":
            ledger["state"] = "completed" if passed == {j["job_id"] for j in manifest["jobs"]} else "waiting_quota_cooldown"
        check_ledger(manifest, ledger)
        save(path, ledger)
        return ledger


def amend_quota(manifest, directory):
    with base.exclusive(directory / "model.lock"):
        ledger = base.read_json(directory / "attempts.json")
        check_ledger(manifest, ledger)
        if manifest["model"] != SONNET or ledger.get("quota_amendment") or ledger["state"] != "paused_quota":
            raise RuntimeError("No unused Sonnet quota amendment available")
        failed = ledger["attempts"][-1]
        if not failed.get("quota_failure"):
            raise RuntimeError("Confirmed quota failure required")
        ledger["quota_amendment"] = {"failed_attempt_id": failed["attempt_id"], "job_id": failed["job_id"],
            "not_before": max(time.time() + 60, failed["retry_not_before"]), "minimum_spacing_s": 65,
            "retained_files": tree_hashes(Path(failed["attempt_root"]))}
        ledger["state"] = "replacement_authorized"
        save(directory / "attempts.json", ledger)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--freeze", action="store_true")
    action.add_argument("--run-model", choices=tuple(CAPS))
    action.add_argument("--amend-sonnet-quota", action="store_true")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--predecessor", type=Path)
    parser.add_argument("--predecessor-ledger", action="append", type=Path)
    parser.add_argument("--confirm-predecessor-drained", action="store_true")
    args = parser.parse_args()
    directory = args.run_dir.resolve()
    if args.freeze:
        if not args.predecessor or not args.predecessor_ledger:
            parser.error("Freeze requires predecessor and explicit model ledgers")
        freeze(directory, args.predecessor.resolve(), args.predecessor_ledger, args.confirm_predecessor_drained)
        return 0
    plan = verify(directory)
    if args.amend_sonnet_quota:
        amend_quota(plan["models"][SONNET], directory / SONNET)
    elif args.run_model:
        with predecessor_locks(Path(plan["predecessor"])):
            for path in plan["predecessor_ledgers"]:
                if any(r["status"] == "running" for r in base.read_json(Path(path))["attempts"]):
                    raise RuntimeError("Predecessor resumed unexpectedly")
        if os.geteuid() != 0 or os.environ.get("STUDY_FAKE_GROK") or not sys.executable:
            raise RuntimeError("Real contained execution identity required")
        if args.run_model == LUNA and not os.environ.get("ROUTE_A_HARNESS_API_KEY"):
            raise RuntimeError("Trusted Luna credential missing")
        if shutil.disk_usage(directory).free < 2 * 1024**3:
            raise RuntimeError("Less than 2 GiB free")
        result = run_model(plan["models"][args.run_model], directory / args.run_model, lambda: base.verify_runtime(plan))
        print("DONE" if result["state"] == "completed" else "FAILED", flush=True)
        return 0 if result["state"] == "completed" else 2
    else:
        print(json.dumps({"verified": True, "inference_called": False,
                          "remaining": {m: len(v["jobs"]) for m, v in plan["models"].items()}}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("FAILED", type(exc).__name__, flush=True)
        raise SystemExit(2)
