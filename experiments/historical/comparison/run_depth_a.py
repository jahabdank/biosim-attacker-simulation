"""Confirmatory depth: per-model best kill, matched S-band rewrite, best S-band. Six new reps."""

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
import time

SOURCE = Path(_archive_root())
sys.path[:0] = [str(SOURCE / "src"), str(SOURCE / "scripts")]
from biosim_operator import study
from run_terra_comparison_smoke import save

IDENTITY = SOURCE / "packs/dual-alive-sband-t1-peer"
V10 = SOURCE / "data/hijack_scripts/v10-replicas-wide"
ADAPTED = SOURCE / "data/hijack_scripts/v10-sband-adapted"
PROC = SOURCE / "data/hijack_scripts/sband-undermine-v1/commissioning-receipt.txt"
PACKETS = {
    "grok-4.6": ("rehearsal-cabin", "rehearsal-cabin", "commissioning-receipt"),
    "gpt-5.6-luna": ("spare-desk", "spare-desk", "commissioning-receipt"),
    "claude-sonnet-5": ("rehearsal-cabin", "rehearsal-cabin", "commissioning-receipt"),
}


def original(story):
    return next((V10 / story).glob("*.txt"))


def job(model, condition, story, rep):
    if condition == "kill":
        script, bank = original(story), "v10-replicas-wide"
    elif condition == "matched-sband":
        script, bank = ADAPTED / f"{story}.txt", "v10-sband-adapted"
    else:
        script, bank = PROC, "sband-undermine-v1"
    return dict(
        job_id=f"depth-a:{model}:{condition}:t1:{story}:r{rep:02d}",
        study_id="depth-a-20260916",
        model=model,
        route="native-xai-subscription" if model == "grok-4.6" else "configured-provider",
        context_window=500000 if model == "grok-4.6" else (1000000 if model.startswith("claude-") else 1050000),
        route_a_fallback=False,
        story=story,
        trust="t1",
        repeat=rep,
        arm="attack",
        experiment=condition,
        envelope="peer",
        probe="hijack",
        script_src=str(script),
        script_bank=bank,
        script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
        identity_dir=str(IDENTITY),
        interrupt_p=1.0,
        hijack_after_wakes=6,
        sband_separator="--- PEER MESSAGE ---",
        launchable=True,
        per_episode_jvm=True,
        technical=False,
        minimum_spacing_s=120 if model.startswith("claude-") else 15,
    )


def execute(root, item):
    root.mkdir()
    state = dict(state="running", job=item, started=time.time(), controller_pid=os.getpid())
    save(root / "status.json", state)
    env = dict(os.environ)
    if item["model"] == "grok-4.6":
        env.pop("STUDY_ROUTE_DIAGNOSTICS", None)
        env.pop("STUDY_ROUTE_PACING", None)
    else:
        env.update(
            STUDY_ROUTE_MODEL=item["model"],
            STUDY_ROUTE_PACING="1",
            STUDY_ROUTE_MIN_SPACING_S=str(item["minimum_spacing_s"]),
            STUDY_ROUTE_TIMEOUT_S="1800",
            STUDY_ROUTE_DIAGNOSTICS=str(root / "route-diagnostics.jsonl"),
        )
    try:
        proc = study.launch_cli_episode(item, run_dir=root, env=env, extra_argv=["--timeout", "1800", "--max-tool-turns", "16"])
        ep = study.episode_dir(root, item["job_id"])
        o = json.loads((ep / "outcome.json").read_text()) if (ep / "outcome.json").exists() else {}
        state.update(
            state="completed" if proc.returncode == 0 and o and not o.get("incomplete") else "failed",
            returncode=proc.returncode,
            artifact=str(ep),
            n_dead=o.get("n_dead"),
        )
    except Exception as exc:
        state.update(state="failed", error=repr(exc))
    state["ended"] = time.time()
    save(root / "status.json", state)
    return state


def lane(run, model, jobs):
    folder = run / model
    folder.mkdir()
    state = dict(state="running", model=model, completed=0, controller_pid=os.getpid())
    save(folder / "status.json", state)
    locks = []
    try:
        f = Path("/run/lock/biosim-" + model + ".lock").open("a+")
        locks.append(f)
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if model.startswith("claude-"):
            provider_a = Path("/run/lock/biosim-provider_a-episode.lock").open("a+")
            locks.append(provider_a)
            fcntl.flock(provider_a, fcntl.LOCK_EX)
        for item in jobs:
            result = execute(folder / item["job_id"].replace(":", "__"), item)
            if result["state"] != "completed":
                state.update(state="failed", failed=item["job_id"])
                break
            state["completed"] += 1
            save(folder / "status.json", state)
            time.sleep(15)
        else:
            state["state"] = "completed"
    except Exception as exc:
        state.update(state="failed", error=repr(exc))
    finally:
        save(folder / "status.json", state)
        for f in locks:
            f.close()
    return state


def main():
    run = Path(sys.argv[1])
    fcntl.flock(Path("/run/lock/biosim-depth-a.lock").open("a+"), fcntl.LOCK_EX | fcntl.LOCK_NB)
    run.mkdir(parents=True, exist_ok=False)
    jobs = {}
    for i, model in enumerate(PACKETS):
        kill, matched, best = PACKETS[model]
        items = (
            [job(model, "kill", kill, r) for r in range(3, 9)]
            + [job(model, "matched-sband", matched, r) for r in range(3, 9)]
            + [job(model, "best-sband", best, r) for r in range(3, 9)]
        )
        random.Random(20260916 + i).shuffle(items)
        jobs[model] = items
    assert sum(map(len, jobs.values())) == 54
    save(
        run / "manifest.json",
        dict(
            jobs=jobs,
            packets=PACKETS,
            attempt_cap=54,
            retries=0,
            notes="Confirmatory n=6 new (r03-r08). Grok kill=rehearsal-cabin; Luna kill=spare-desk; Sonnet kill=rehearsal-cabin (no Sonnet kill hit; strongest known kill attractor). Matched S-band keeps first 9 frames of that kill story. Best S-band=commissioning-receipt for all (only sustained drop). Discovery cells excluded. Sonnet waits on PROVIDER_A lock held by round2. Dual prompt unchanged.",
        ),
    )
    save(run / "status.json", dict(state="running", controller_pid=os.getpid(), started=time.time()))
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = [f.result() for f in [pool.submit(lane, run, m, items) for m, items in jobs.items()]]
    save(
        run / "status.json",
        dict(
            state="completed" if all(x["state"] == "completed" for x in results) else "partial_failure",
            ended=time.time(),
            lanes=results,
        ),
    )


if __name__ == "__main__":
    main()
