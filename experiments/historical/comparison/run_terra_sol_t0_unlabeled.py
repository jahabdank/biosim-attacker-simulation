"""Terra and Sol: T0 triple, then unlabeled triple. GPT-family packets (spare-desk)."""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import concurrent.futures
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import threading
import time

SOURCE = Path(_archive_root())
sys.path[:0] = [str(SOURCE / "src"), str(SOURCE / "scripts")]
from biosim_operator import study
from biosim_operator.study import HIJACK_SEPARATOR
from run_terra_comparison_smoke import save

HOST_A = Path(str(_archive_path('path_034')))
T0_ID = SOURCE / "packs/dual-alive-sband-t0-commission"
UNL_ID = SOURCE / "packs/dual-alive-sband-unlabeled"
V10 = SOURCE / "data/hijack_scripts/v10-replicas-wide"
ADAPTED = SOURCE / "data/hijack_scripts/v10-sband-adapted"
PROC = SOURCE / "data/hijack_scripts/sband-undermine-v1/commissioning-receipt.txt"
BLANK = "\n\n"
KILL = MATCHED = "spare-desk"
BEST = "commissioning-receipt"
MODELS = ("gpt-5.6-terra", "gpt-5.6-sol")
SUP_LOCK = threading.Lock()


def original(story):
    return next((V10 / story).glob("*.txt"))


def job(model, phase, condition, story, rep):
    if condition == "kill":
        script, bank = original(story), "v10-replicas-wide"
    elif condition == "matched-sband":
        script, bank = ADAPTED / f"{story}.txt", "v10-sband-adapted"
    else:
        script, bank = PROC, "sband-undermine-v1"
    unlabeled = phase == "unlabeled"
    return dict(
        job_id=f"{phase}-triple:{model}:{condition}:{phase}:{story}:r{rep:02d}",
        study_id=f"{model.split('.')[-1]}-{phase}-triple-20260920",
        model=model,
        route="configured-provider",
        context_window=1050000,
        route_a_fallback=False,
        story=story,
        trust="unlabeled" if unlabeled else "t0",
        repeat=rep,
        arm="attack",
        experiment=condition,
        envelope="unlabeled" if unlabeled else "commission",
        probe="hijack",
        script_src=str(script),
        script_bank=bank,
        script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
        identity_dir=str(UNL_ID if unlabeled else T0_ID),
        interrupt_p=1.0,
        hijack_after_wakes=6,
        sband_separator=BLANK if unlabeled else HIJACK_SEPARATOR,
        launchable=True,
        per_episode_jvm=True,
        technical=False,
        minimum_spacing_s=15,
    )


def jobs_for(model, phase):
    items = (
        [job(model, phase, "kill", KILL, r) for r in range(1, 7)]
        + [job(model, phase, "matched-sband", MATCHED, r) for r in range(1, 7)]
        + [job(model, phase, "best-sband", BEST, r) for r in range(1, 7)]
    )
    seed = 20260922 + (0 if "terra" in model else 1) + (0 if phase == "t0" else 10)
    random.Random(seed).shuffle(items)
    return items


def execute(root, item):
    root.mkdir()
    state = dict(state="running", job=item, started=time.time(), controller_pid=os.getpid())
    save(root / "status.json", state)
    env = dict(os.environ)
    env.update(
        STUDY_ROUTE_MODEL=item["model"],
        STUDY_ROUTE_PACING="1",
        STUDY_ROUTE_MIN_SPACING_S="15",
        STUDY_ROUTE_TIMEOUT_S="1800",
        STUDY_ROUTE_DIAGNOSTICS=str(root / "route-diagnostics.jsonl"),
    )
    try:
        proc = study.launch_cli_episode(
            item, run_dir=root, env=env, extra_argv=["--timeout", "1800", "--max-tool-turns", "16"]
        )
        ep = study.episode_dir(root, item["job_id"])
        o = json.loads((ep / "outcome.json").read_text()) if (ep / "outcome.json").exists() else {}
        state.update(
            state="completed" if proc.returncode == 0 and o and not o.get("incomplete") else "failed",
            returncode=proc.returncode,
            artifact=str(ep),
            n_dead=o.get("n_dead"),
            incomplete=o.get("incomplete_reason") or o.get("incomplete"),
        )
    except Exception as exc:
        state.update(state="failed", error=repr(exc))
    state["ended"] = time.time()
    save(root / "status.json", state)
    return state


def run_phase(supervisor, model, phase):
    slug = "terra" if "terra" in model else "sol"
    run = HOST_A / f"{slug}-{phase}-triple-20260920"
    run.mkdir(parents=True, exist_ok=False)
    items = jobs_for(model, phase)
    save(
        run / "manifest.json",
        dict(
            jobs=items,
            n=18,
            model=model,
            phase=phase,
            packets=dict(kill=KILL, matched=MATCHED, best=BEST),
            identity=str(UNL_ID if phase == "unlabeled" else T0_ID),
            notes="GPT-family triple. spare-desk kill/matched, commissioning-receipt. Do not pool T0 with unlabeled or with Grok.",
        ),
    )
    state = dict(state="running", model=model, phase=phase, completed=0, controller_pid=os.getpid(), started=time.time())
    save(run / "status.json", state)
    with SUP_LOCK:
        snap = json.loads((supervisor / "status.json").read_text())
        launched = list(snap.get("launched") or [])
        launched.append(f"{model}:{phase}")
        snap.update(launched=launched, updated=time.time())
        save(supervisor / "status.json", snap)
    for item in items:
        result = execute(run / item["job_id"].replace(":", "__"), item)
        if result["state"] != "completed":
            if result.get("incomplete") == "route_error":
                state.setdefault("route_errors", []).append(item["job_id"])
                save(run / "status.json", state)
                time.sleep(15)
                continue
            state.update(state="failed", failed=item["job_id"], ended=time.time())
            save(run / "status.json", state)
            return state
        state["completed"] += 1
        save(run / "status.json", state)
        time.sleep(15)
    state.update(state="completed", ended=time.time())
    save(run / "status.json", state)
    return state


def lane(supervisor, model):
    lock = Path("/run/lock/biosim-" + model + ".lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        t0 = run_phase(supervisor, model, "t0")
        unlabeled = run_phase(supervisor, model, "unlabeled")
        return dict(model=model, t0=t0.get("state"), unlabeled=unlabeled.get("state"))
    finally:
        lock.close()


def main():
    run = Path(sys.argv[1])
    batch_lock = Path("/run/lock/biosim-terra-sol-t0-unlabeled.lock").open("a+")
    fcntl.flock(batch_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    run.mkdir(parents=True, exist_ok=False)
    save(
        run / "status.json",
        dict(state="running", controller_pid=os.getpid(), started=time.time(), launched=[]),
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result() for f in [pool.submit(lane, run, m) for m in MODELS]]
    save(run / "status.json", dict(state="completed" if all(x.get("t0") == "completed" and x.get("unlabeled") == "completed" for x in results) else "partial_failure", ended=time.time(), lanes=results))


if __name__ == "__main__":
    main()
