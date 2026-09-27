#!/usr/bin/env python3
"""Bounded next46 controller. Freeze and verification never invoke inference."""
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
import hashlib
import json
import os
import random
from pathlib import Path
import shutil
import sys
import time
import uuid
from collections import Counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from biosim_operator import study
from biosim_operator.paths import runs_root
from run_first_batch import save, verify as verify_runtime
from sonnet_pacing import validate_spacing

SONNET = "claude-sonnet-5"
GROK = "grok-4.6"
LUNA = "gpt-5.6-luna"
CAPS = {SONNET: 1, GROK: 4, LUNA: 3}
COUNTS = {SONNET: 10, GROK: 24, LUNA: 12}
ORDER_SEED = 2026090746
DEFAULT = runs_root() / "20260907-next46"
PREVIOUS = runs_root() / "20260907-research50-grok-luna/attempts.json"
FILES = ["scripts/study/run_next_batch.py", "scripts/study/run_first_batch.py",
         "scripts/study/route_broker.py", "scripts/study/sonnet_pacing.py",
         "scripts/study/connect_proxy.py"]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select_jobs(completed: set[str] = frozenset()) -> list[dict]:
    jobs = []
    for j in study.build_full_manifest():
        m, arm, trust, repeat = j["model"], j["arm"], j["trust"], j["repeat"]
        wanted = (
            m == SONNET and repeat == 1 and (arm == "attack" or arm == "control" and trust == "t1")
            or m == GROK and trust in {"t1", "t2"} and (
                arm == "attack" and repeat in {3, 4, 5} or arm == "envelope" and repeat == 2)
            or m == LUNA and (arm == "attack" and repeat == 3 or arm == "control" and repeat == 2)
        )
        if wanted:
            jobs.append(j)
    ids = [j["job_id"] for j in jobs]
    if len(ids) != len(set(ids)) or Counter(j["model"] for j in jobs) != COUNTS:
        raise RuntimeError("next46 allocation mismatch")
    if set(ids) & completed:
        raise RuntimeError("Selected scientific IDs already completed")
    rng = random.Random(ORDER_SEED)
    phases = [[j for j in jobs if (j["arm"] == "control") == control] for control in (True, False)]
    for phase in phases:
        rng.shuffle(phase)
    return phases[0] + phases[1]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def incomplete_json(text: str, exc: json.JSONDecodeError) -> bool:
    if not text.strip():
        return True
    if exc.msg.startswith("Unterminated string"):
        return True
    if exc.msg.startswith("Invalid \\uXXXX escape"):
        suffix = text[exc.pos:]
        return suffix.startswith("u") and len(suffix) < 5 and all(c in "0123456789abcdefABCDEF" for c in suffix[1:])
    if exc.pos >= len(text.rstrip()):
        return True
    if exc.msg == "Expecting ',' delimiter":
        suffix = text[exc.pos:]
        if suffix in {".", "e", "E", "e+", "e-", "E+", "E-"}:
            return True
    suffix = text[exc.pos:].strip()
    return exc.msg == "Expecting value" and (suffix == "-" or any(word.startswith(suffix) for word in ("true", "false", "null")))


def read_active_json(path: Path) -> dict | None:
    text = path.read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        if not text.endswith("\n") and incomplete_json(text, exc):
            return None
        raise


def read_events(path: Path, *, active: bool = False) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text().splitlines(keepends=True)
    records = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            if active and i == len(lines) - 1 and not line.endswith("\n") and incomplete_json(line, exc):
                break
            raise
    return records


def inspect_artifacts(job: dict, artifact: Path, returncode: int) -> dict:
    missing = study.required_artifacts(artifact)
    if missing:
        return {"status": "missing_artifact", "missing": missing}
    outcome = read_json(artifact / "outcome.json")
    card = read_json(artifact / "card.json")
    transcript = read_events(artifact / "transcript.jsonl")
    wakes = [read_json(p) for p in sorted((artifact / "wakes").glob("*.json"))]
    score = outcome.get("score", {})
    dead, crew = outcome.get("n_dead", score.get("n_dead")), outcome.get("n_crew", score.get("n_crew"))
    hours = score.get("hours", 0)
    roster = outcome.get("crew", [])
    errors = []
    if outcome.get("cell_id") != job["job_id"] or card.get("cell_id") != job["job_id"]:
        errors.append("cell_identity")
    if outcome.get("model") != job["model"] or card.get("model") != job["model"]:
        errors.append("model_identity")
    if not transcript or not wakes or len(wakes) > 24:
        errors.append("missing_transcript_or_watches")
    if any(w.get("timed_out") or w.get("returncode") != 0 for w in wakes):
        errors.append("watch_error")
    if [w.get("turn") for w in wakes] != list(range(1, len(wakes) + 1)):
        errors.append("watch_sequence")
    if crew != 4 or len(roster) != 4 or sum(c.get("alive") is False for c in roster) != dead:
        errors.append("roster")
    horizon = 119.99 <= hours <= 120.01 and len(wakes) == 24
    if not horizon and not (dead == 4 and 24 <= hours < 120):
        errors.append("terminal_condition")
    if job["arm"] == "control" and (not horizon or dead != 0):
        errors.append("control_survival")
    status = study.classify_attempt(returncode=returncode, outcome=outcome, missing=[])
    if outcome.get("status") != "complete" or outcome.get("incomplete"):
        status = "incomplete"
    if errors and status == "ok":
        status = "invalid_artifact"
    return {"status": status, "validation_errors": errors, "n_dead": dead, "n_crew": crew,
            "hours": hours, "watches": len(wakes)}


def completed_ids(paths: list[Path], *, validate_artifacts: bool = True) -> set[str]:
    ids = set()
    for path in paths:
        ledger = read_json(path)
        if ledger.get("state") != "completed":
            raise RuntimeError("Prior research ledger is not completed")
        rows = ledger["attempts"]
        successful = [r for r in rows if r["status"] == "ok"]
        for row in successful:
            if row["job_id"] in ids:
                raise RuntimeError("Duplicate completed scientific ID across prior ledgers")
            job = next((j for j in study.build_full_manifest() if j["job_id"] == row["job_id"]), None)
            if job is None or validate_artifacts and inspect_artifacts(job, Path(row["artifact"]), row["returncode"])["status"] != "ok":
                raise RuntimeError("Prior completed artifact validation failed")
            ids.add(row["job_id"])
    return ids


def archive_inputs(destination: Path) -> dict:
    if destination.exists():
        raise RuntimeError("Input archive already exists; refusing overwrite")
    study.archive_runtime_sources(destination)
    for rel in FILES:
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)
    return {str(p.relative_to(destination)): digest(p) for p in sorted(destination.rglob("*")) if p.is_file()}


def freeze(run_dir: Path, prior: list[Path], spacing: float) -> None:
    spacing = validate_spacing(spacing)
    if spacing != 20:
        raise RuntimeError("Approved next46 initial spacing is 20 seconds")
    if run_dir.exists():
        raise RuntimeError("Freeze requires a fresh directory")
    ids = completed_ids(prior)
    jobs = select_jobs(ids)
    if not {j["job_id"] for j in study.build_full_manifest() if j["model"] == GROK
            and j["arm"] == "control" and j["repeat"] == 1} <= ids:
        raise RuntimeError("Prior Grok controls missing")
    fingerprints = study.collect_fingerprints()
    images = fingerprints.get("docker_images", {})
    if not images.get("available") or not images.get("images") or not all(isinstance(v, dict) and v.get("present") for v in images["images"].values()):
        raise RuntimeError("Freeze requires accessible, present Docker images under the execution identity")
    run_dir.mkdir(parents=True)
    archive = archive_inputs(run_dir / "frozen-inputs")
    batch_files = {rel: digest(ROOT / rel) for rel in FILES}
    prior_hashes = {str(p.resolve()): digest(p) for p in prior}
    models = {}
    for model in CAPS:
        directory = run_dir / model
        directory.mkdir()
        manifest = {"model": model, "order_seed": ORDER_SEED,
                    "jobs": [j for j in jobs if j["model"] == model],
                    "concurrency": CAPS[model], "timeout_s": 900 if model == SONNET else 480,
                    "minimum_spacing_s": spacing if model == SONNET else None,
                    "replacement_spacing_s": 65 if model == SONNET else None,
                    "quota_window_s": 60, "max_replacements": int(model == SONNET),
                    "max_attempts": COUNTS[model] + int(model == SONNET),
                    "fingerprints": fingerprints, "batch_files": batch_files,
                    "prior_ledgers": prior_hashes}
        save(directory / "manifest.json", manifest)
        models[model] = digest(directory / "manifest.json")
    save(run_dir / "manifest.json", {"models": models, "archive": archive,
         "prior_ledgers": prior_hashes, "max_cells": 46, "max_attempts": 47,
         "global_concurrency": 8, "created": time.time()})


def verify(run_dir: Path, *, validate_prior: bool = True) -> dict[str, dict]:
    root = read_json(run_dir / "manifest.json")
    if set(root["models"]) != set(CAPS) or root["max_cells"] != 46 or root["max_attempts"] != 47 or root["global_concurrency"] != 8:
        raise RuntimeError("Batch bounds changed")
    for path, sha in root["prior_ledgers"].items():
        if digest(Path(path)) != sha:
            raise RuntimeError("Prior research ledger changed")
    expected = select_jobs(completed_ids([Path(p) for p in root["prior_ledgers"]], validate_artifacts=validate_prior))
    for rel, sha in root["archive"].items():
        if digest(run_dir / "frozen-inputs" / rel) != sha:
            raise RuntimeError("Frozen input archive changed")
    manifests = {}
    for model, sha in root["models"].items():
        path = run_dir / model / "manifest.json"
        if digest(path) != sha:
            raise RuntimeError("Model manifest changed")
        m = read_json(path)
        if m["order_seed"] != ORDER_SEED or m["jobs"] != [j for j in expected if j["model"] == model] or m["concurrency"] != CAPS[model]:
            raise RuntimeError("Frozen selection or concurrency changed")
        if m["timeout_s"] != (900 if model == SONNET else 480) or m["minimum_spacing_s"] != (20 if model == SONNET else None):
            raise RuntimeError("Frozen pacing or timeout changed")
        if m["max_attempts"] != COUNTS[model] + int(model == SONNET) or m["max_replacements"] != int(model == SONNET):
            raise RuntimeError("Frozen attempt cap changed")
        if m["replacement_spacing_s"] != (65 if model == SONNET else None) or m["quota_window_s"] != 60:
            raise RuntimeError("Frozen replacement policy changed")
        verify_runtime(m)
        manifests[model] = m
    return manifests


def attempt_env(manifest: dict, attempt_root: Path, spacing: float | None) -> dict:
    env = os.environ.copy()
    for name in ("STUDY_SONNET_PACING", "STUDY_SONNET_MIN_SPACING_S", "STUDY_ROUTE_DIAGNOSTICS"):
        env.pop(name, None)
    if manifest["model"] == SONNET:
        env["STUDY_SONNET_PACING"] = "1"
        env["STUDY_SONNET_MIN_SPACING_S"] = str(validate_spacing(spacing))
    if manifest["model"] in {LUNA, SONNET}:
        env["STUDY_ROUTE_DIAGNOSTICS"] = str(attempt_root / "route-diagnostics.jsonl")
    return env


def execute(job: dict, manifest: dict, row: dict) -> dict:
    attempt_root = Path(row["attempt_root"])
    artifact = study.episode_dir(attempt_root, job["job_id"])
    try:
        proc = study.launch_cli_episode(job, run_dir=attempt_root,
            env=attempt_env(manifest, attempt_root, row["minimum_spacing_s"]),
            extra_argv=["--timeout", str(manifest["timeout_s"])])
        result = inspect_artifacts(job, artifact, proc.returncode)
        result["returncode"] = proc.returncode
        result["usage"] = study.collect_attempt_usage(artifact)
    except Exception as exc:
        result = {"status": "failed", "error_type": type(exc).__name__}
    try:
        events = read_events(attempt_root / "route-diagnostics.jsonl")
    except json.JSONDecodeError:
        events = []
        result.update(status="incomplete", error_type="DiagnosticParseError")
    quotas = [e for e in events if e.get("status") == 429]
    if quotas:
        quota_requests = {e.get("request_id") for e in quotas}
        cooldown_events = quotas + [e for e in events if e.get("request_id") in quota_requests and e.get("retry_after_s")]
        result.update(status="incomplete", quota_failure=True,
                      retry_not_before=max(e["at"] + max(manifest["quota_window_s"], e.get("retry_after_s") or 0) for e in cooldown_events))
    elif any(e.get("event") == "transport_error" or e.get("status", 0) >= 400 for e in events):
        result["status"] = "incomplete"
    result.update(artifact=str(artifact), ended=time.time(), elapsed_s=time.time() - row["started"])
    return result


def check_ledger(manifest: dict, ledger: dict) -> None:
    rows = ledger["attempts"]
    allowed = {j["job_id"] for j in manifest["jobs"]}
    if len(rows) > manifest["max_attempts"] or any(r["job_id"] not in allowed for r in rows):
        raise RuntimeError("Attempt cap or scientific ID violation")
    replacements = [r for r in rows if r.get("replacement_of")]
    if len(replacements) > manifest["max_replacements"]:
        raise RuntimeError("Replacement cap exceeded")
    if len({r["attempt_id"] for r in rows}) != len(rows):
        raise RuntimeError("Duplicate attempt ID")
    for cell, count in Counter(r["job_id"] for r in rows).items():
        if count > 1:
            pair = [r for r in rows if r["job_id"] == cell]
            if count != 2 or pair[1].get("replacement_of") != pair[0]["attempt_id"] or not pair[0].get("quota_failure"):
                raise RuntimeError("Unamended duplicate admission")
    for row in replacements:
        amendment = ledger.get("amendment", {})
        if amendment.get("failed_attempt_id") != row["replacement_of"] or row["minimum_spacing_s"] != 65:
            raise RuntimeError("Replacement amendment missing or invalid")
    if any(r["status"] == "running" for r in rows):
        raise RuntimeError("Interrupted admission: reconcile explicitly after proving child processes stopped; no automatic retry")


def controls_passed(manifest: dict, ledger: dict) -> bool:
    controls = {j["job_id"] for j in manifest["jobs"] if j["arm"] == "control"}
    passed = {r["job_id"] for r in ledger["attempts"] if r["status"] == "ok"}
    return controls <= passed


def amend(manifest: dict, ledger: dict, directory: Path) -> None:
    check_ledger(manifest, ledger)
    rows = ledger["attempts"]
    if manifest["replacement_spacing_s"] != 65 or manifest["quota_window_s"] < 60:
        raise RuntimeError("Invalid replacement policy")
    if manifest["model"] != SONNET or ledger["state"] != "paused_quota" or not rows or not rows[-1].get("quota_failure"):
        raise RuntimeError("No eligible Sonnet quota failure")
    if any(r.get("replacement_of") for r in rows) or ledger.get("amendment"):
        raise RuntimeError("Only one quota amendment is authorized")
    failed = rows[-1]
    archive = Path(failed["attempt_root"])
    tree = {str(p.relative_to(archive)): digest(p) for p in archive.rglob("*") if p.is_file()}
    if not tree:
        raise RuntimeError("Failed attempt artifacts unavailable")
    amendment = {"failed_attempt_id": failed["attempt_id"], "job_id": failed["job_id"],
                 "reason": "Confirmed HTTP or stream quota error: single authorized 65-second technical replacement",
                 "minimum_spacing_s": 65, "not_before": max(time.time() + 60, failed["retry_not_before"]),
                 "retained_artifact_tree": tree, "created": time.time()}
    path = directory / "quota-amendment.json"
    if path.exists():
        raise RuntimeError("Existing amendment requires reconciliation; refusing overwrite")
    save(path, amendment)
    ledger.update(amendment=amendment, state="replacement_authorized")
    save(directory / "attempts.json", ledger)


def admit(manifest: dict, ledger: dict, directory: Path, job: dict, replacement: dict | None = None) -> dict:
    if len(ledger["attempts"]) >= manifest["max_attempts"]:
        raise RuntimeError("Attempt cap reached")
    prior = [r for r in ledger["attempts"] if r["job_id"] == job["job_id"]]
    if prior and not replacement:
        raise RuntimeError("Duplicate scientific admission")
    spacing = manifest["minimum_spacing_s"]
    amendment = ledger.get("amendment")
    if amendment:
        spacing = amendment["minimum_spacing_s"]
    if replacement:
        if len(prior) != 1 or replacement is not prior[0] or any(r.get("replacement_of") for r in ledger["attempts"]):
            raise RuntimeError("Replacement cap or lineage violation")
        if not amendment or amendment["failed_attempt_id"] != replacement["attempt_id"] or time.time() < amendment["not_before"]:
            raise RuntimeError("Replacement not authorized or cooldown not elapsed")
        for rel, sha in amendment["retained_artifact_tree"].items():
            if digest(Path(replacement["attempt_root"]) / rel) != sha:
                raise RuntimeError("Retained failed artifacts changed")
    attempt_id = uuid.uuid4().hex
    attempt_root = directory / "attempts" / attempt_id
    attempt_root.mkdir(parents=True)
    row = {"attempt_id": attempt_id, "job_id": job["job_id"], "model": job["model"],
           "arm": job["arm"], "trust": job["trust"], "status": "running", "started": time.time(),
           "attempt_root": str(attempt_root), "minimum_spacing_s": spacing,
           "timeout_s": manifest["timeout_s"], "replacement_of": replacement["attempt_id"] if replacement else None}
    ledger["attempts"].append(row)
    save(directory / "attempts.json", ledger)
    return row


def run_model(manifest: dict, directory: Path, verify_callback=lambda: None) -> dict:
    with exclusive(directory / "model.lock"):
        return _run_model(manifest, directory, verify_callback)


def _run_model(manifest: dict, directory: Path, verify_callback) -> dict:
    path = directory / "attempts.json"
    ledger = read_json(path) if path.exists() else {"attempts": [], "state": "ready"}
    check_ledger(manifest, ledger)
    for row in ledger["attempts"]:
        if row["status"] == "ok":
            job = next(j for j in manifest["jobs"] if j["job_id"] == row["job_id"])
            if inspect_artifacts(job, Path(row["artifact"]), row["returncode"])["status"] != "ok":
                raise RuntimeError("Previously successful artifacts no longer validate")
    if ledger["state"].startswith("paused"):
        return ledger
    amendment = ledger.get("amendment")
    if amendment and read_json(directory / "quota-amendment.json") != amendment:
        raise RuntimeError("Amendment changed")
    replacement = None
    if ledger["state"] == "replacement_authorized":
        replacement = next(r for r in ledger["attempts"] if r["attempt_id"] == amendment["failed_attempt_id"])
        if time.time() < amendment["not_before"]:
            return ledger
    tried = {r["job_id"] for r in ledger["attempts"]}
    pending = [j for j in manifest["jobs"] if j["job_id"] not in tried]
    if replacement:
        pending.insert(0, next(j for j in manifest["jobs"] if j["job_id"] == replacement["job_id"]))
    ledger["state"] = "running"
    running = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=manifest["concurrency"]) as pool:
        while pending or running:
            if (directory / "PAUSE-AFTER-CURRENT").exists() or (directory.parent / "PAUSE-AFTER-CURRENT").exists():
                ledger["state"] = "paused_operator_request"
            previous_state = ledger["state"]
            for future, row in running.items():
                root = Path(row["attempt_root"])
                active = not future.done()
                try:
                    events = read_events(root / "route-diagnostics.jsonl", active=active)
                except json.JSONDecodeError:
                    events = []
                    ledger["state"] = "paused_diagnostic_parse_failure"
                if any(e.get("status") == 429 for e in events):
                    ledger["state"] = "paused_quota"
                elif any(e.get("event") == "transport_error" or e.get("status", 0) >= 400 for e in events):
                    ledger["state"] = "paused_technical_failure"
                wakes = sorted(study.episode_dir(root, row["job_id"]).glob("wakes/*.json"))
                for index, wake in enumerate(wakes):
                    try:
                        w = read_active_json(wake) if active and index == len(wakes) - 1 else read_json(wake)
                        if w is None:
                            continue
                    except json.JSONDecodeError:
                        ledger["state"] = "paused_watch_parse_failure"
                        continue
                    if w.get("timed_out") or w.get("returncode") != 0:
                        if ledger["state"] != "paused_quota":
                            ledger["state"] = "paused_technical_failure"
            if ledger["state"] != previous_state:
                print("FAILED", manifest["model"], ledger["state"], flush=True)
            save(path, ledger)
            if ledger["state"] == "running":
                for job in list(pending):
                    if len(running) >= manifest["concurrency"]:
                        break
                    if job["arm"] != "control" and not controls_passed(manifest, ledger):
                        continue
                    verify_callback()
                    row = admit(manifest, ledger, directory, job, replacement if replacement and job["job_id"] == replacement["job_id"] else None)
                    pending.remove(job)
                    running[pool.submit(execute, job, manifest, row)] = row
            if not running:
                break
            done, _ = concurrent.futures.wait(running, timeout=1, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                row = running.pop(future)
                try:
                    row.update(future.result())
                except Exception as exc:
                    row.update(status="failed", error_type=type(exc).__name__, ended=time.time())
                if row["status"] == "ok":
                    try:
                        root = Path(row["attempt_root"])
                        read_events(root / "route-diagnostics.jsonl")
                        for wake in study.episode_dir(root, row["job_id"]).glob("wakes/*.json"):
                            read_json(wake)
                    except (OSError, ValueError):
                        row.update(status="incomplete", error_type="CompletionParseError")
                if row["status"] != "ok":
                    ledger["state"] = "paused_quota" if row.get("quota_failure") else "paused_technical_failure"
                    print("FAILED", manifest["model"], ledger["state"], flush=True)
                save(path, ledger)
        successful = {r["job_id"] for r in ledger["attempts"] if r["status"] == "ok"}
        if successful == {j["job_id"] for j in manifest["jobs"]} and ledger["state"] == "running":
            ledger["state"] = "completed"
        elif ledger["state"] == "running":
            ledger["state"] = "paused_incomplete"
        check_ledger(manifest, ledger)
        save(path, ledger)
    return ledger


@contextlib.contextmanager
def exclusive(path: Path):
    with path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock.seek(0)
        lock.truncate()
        lock.write(json.dumps({"pid": os.getpid(), "started": time.time()}))
        lock.flush()
        yield


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--freeze", action="store_true")
    action.add_argument("--run", action="store_true")
    action.add_argument("--amend-sonnet-quota", action="store_true")
    action.add_argument("--reconcile-model", choices=tuple(CAPS))
    parser.add_argument("--run-dir", type=Path, default=DEFAULT)
    parser.add_argument("--prior-ledger", type=Path, action="append")
    parser.add_argument("--sonnet-spacing", type=validate_spacing, default=20)
    parser.add_argument("--confirm-children-stopped", action="store_true")
    args = parser.parse_args()
    directory = args.run_dir.resolve()
    if args.freeze:
        freeze(directory, args.prior_ledger or [PREVIOUS], args.sonnet_spacing)
        print(json.dumps({"frozen": str(directory), "cells": 46, "inference_called": False}))
        return 0
    manifests = verify(directory)
    if not args.run and not args.amend_sonnet_quota and not args.reconcile_model:
        print(json.dumps({"verified": True, "cells": 46, "caps": CAPS, "inference_called": False}))
        return 0
    lock_path = directory / "runner.lock"
    if args.amend_sonnet_quota:
        lock_path = directory / SONNET / "model.lock"
    elif args.reconcile_model:
        lock_path = directory / args.reconcile_model / "model.lock"
    with exclusive(lock_path):
        if args.reconcile_model:
            if not args.confirm_children_stopped:
                raise RuntimeError("Reconciliation requires operator verification that owned children have stopped")
            model_dir = directory / args.reconcile_model
            ledger = read_json(model_dir / "attempts.json")
            save(model_dir / ("before-reconciliation-" + uuid.uuid4().hex + ".json"), ledger)
            for row in ledger["attempts"]:
                if row["status"] == "running":
                    row.update(status="incomplete", reconciliation="operator confirmed children stopped", ended=time.time())
                    events = read_events(Path(row["attempt_root"]) / "route-diagnostics.jsonl")
                    quotas = [e for e in events if e.get("status") == 429]
                    if quotas:
                        requests = {e.get("request_id") for e in quotas}
                        cooldown = quotas + [e for e in events if e.get("request_id") in requests and e.get("retry_after_s")]
                        row.update(quota_failure=True, retry_not_before=max(e["at"] + max(60, e.get("retry_after_s") or 0) for e in cooldown))
            ledger["state"] = "paused_quota" if ledger["attempts"] and ledger["attempts"][-1].get("quota_failure") else "paused_reconciled"
            check_ledger(manifests[args.reconcile_model], ledger)
            save(model_dir / "attempts.json", ledger)
            return 0
        if args.amend_sonnet_quota:
            model_dir = directory / SONNET
            amend(manifests[SONNET], read_json(model_dir / "attempts.json"), model_dir)
            print(json.dumps({"amendment_recorded": True, "inference_called": False}))
            return 0
        if os.geteuid() != 0:
            raise RuntimeError("Contained execution requires sudo")
        if os.environ.get("STUDY_FAKE_GROK"):
            raise RuntimeError("Production runner refuses fake harness")
        if not os.environ.get("ROUTE_A_HARNESS_API_KEY"):
            raise RuntimeError("Trusted controller provider_a credential missing")
        if shutil.disk_usage(directory).free < 2 * 1024**3:
            raise RuntimeError("Less than 2 GiB free; pause for disk review")
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(run_model, m, directory / model, lambda: verify(directory, validate_prior=False)): model for model, m in manifests.items()}
            for future in concurrent.futures.as_completed(futures):
                model = futures[future]
                try:
                    results[model] = future.result()
                except Exception as exc:
                    results[model] = {"state": "paused_controller_error", "error_type": type(exc).__name__}
                    print("FAILED", model, "paused_controller_error", flush=True)
                save(directory / "controller-status.json", {m: r["state"] for m, r in results.items()})
        for model in results:
            path = directory / model / "attempts.json"
            if path.exists() and results[model]["state"] != "paused_controller_error":
                with exclusive(directory / model / "model.lock"):
                    results[model] = read_json(path)
        save(directory / "controller-status.json", {m: r["state"] for m, r in results.items()})
        completed = all(r["state"] == "completed" for r in results.values())
        if completed:
            total = sum(len(r["attempts"]) for r in results.values())
            cells = [r["job_id"] for ledger in results.values() for r in ledger["attempts"] if r["status"] == "ok"]
            if total > 47 or len(cells) != 46 or len(set(cells)) != 46:
                raise RuntimeError("Final batch cap or unique-cell check failed")
        print("DONE" if completed else "FAILED", flush=True)
        return 0 if completed else 2


if __name__ == "__main__":
    raise SystemExit(main())
