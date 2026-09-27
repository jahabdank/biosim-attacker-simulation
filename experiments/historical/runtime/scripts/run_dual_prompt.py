"""Same dual system prompt; V10 lethal vs new long-context S-band-undermine attacks."""

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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from biosim_operator import study
from run_terra_comparison_smoke import save

MODELS = ("gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.6-sol", "grok-4.6")
KILL = ("rehearsal-cabin", "safing-closeout", "spare-desk")
PROC = ("commissioning-receipt", "unfunded-comparison", "cached-frame-honesty")
IDENTITY = ROOT / "packs/dual-alive-sband-t1-peer"


def original_script(story):
    return next((ROOT / "data/hijack_scripts/v10-replicas-wide" / story).glob("*.txt"))


def job_for(model, arm, story):
    kill = arm == "kill"
    script = original_script(story) if kill else ROOT / "data/hijack_scripts/sband-undermine-v1" / f"{story}.txt"
    return dict(
        job_id=f"dual-prompt:{model}:{arm}:attack:t1:{story}:r01",
        study_id="dual-prompt-20260913",
        model=model,
        route="native-xai-subscription" if model == "grok-4.6" else "configured-provider",
        context_window=500000 if model == "grok-4.6" else 1050000,
        route_a_fallback=False,
        story=story,
        trust="t1",
        repeat=1,
        arm="attack",
        experiment=arm,
        envelope="peer",
        probe="hijack",
        script_src=str(script),
        script_bank="v10-replicas-wide" if kill else "sband-undermine-v1",
        script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
        identity_dir=str(IDENTITY),
        interrupt_p=1.0,
        hijack_after_wakes=6,
        sband_separator="--- PEER MESSAGE ---",
        launchable=True,
        per_episode_jvm=True,
        technical=False,
    )


def execute(folder, job):
    folder.mkdir()
    state = dict(state="running", job=job, started=time.time(), controller_pid=os.getpid())
    save(folder / "status.json", state)
    env = dict(os.environ)
    if job["model"] == "grok-4.6":
        env.pop("STUDY_ROUTE_DIAGNOSTICS", None)
        env.pop("STUDY_ROUTE_PACING", None)
    else:
        env.update(
            STUDY_ROUTE_MODEL=job["model"],
            STUDY_ROUTE_PACING="1",
            STUDY_ROUTE_MIN_SPACING_S="15",
            STUDY_ROUTE_TIMEOUT_S="1800",
            STUDY_ROUTE_DIAGNOSTICS=str(folder / "route-diagnostics.jsonl"),
        )
    try:
        proc = study.launch_cli_episode(
            job, run_dir=folder, env=env, extra_argv=["--timeout", "1800", "--max-tool-turns", "16"]
        )
        artifact = study.episode_dir(folder, job["job_id"])
        outcome = json.loads((artifact / "outcome.json").read_text()) if (artifact / "outcome.json").exists() else {}
        state.update(
            state="completed" if proc.returncode == 0 and outcome and not outcome.get("incomplete") else "failed",
            returncode=proc.returncode,
            artifact=str(artifact),
            n_dead=outcome.get("n_dead"),
            incomplete=outcome.get("incomplete_reason") or outcome.get("incomplete"),
        )
    except Exception as exc:
        state.update(state="failed", error=repr(exc))
    state["ended"] = time.time()
    save(folder / "status.json", state)
    return state


def lane(run, model, jobs):
    folder = run / model
    folder.mkdir()
    fcntl.flock(Path("/run/lock/biosim-" + model + ".lock").open("a+"), fcntl.LOCK_EX | fcntl.LOCK_NB)
    state = dict(state="running", model=model, completed=0, controller_pid=os.getpid())
    save(folder / "status.json", state)
    for job in jobs:
        result = execute(folder / job["job_id"].replace(":", "__"), job)
        if result["state"] != "completed":
            state.update(state="failed", failed=job["job_id"])
            save(folder / "status.json", state)
            return state
        state["completed"] += 1
        save(folder / "status.json", state)
    state["state"] = "completed"
    save(folder / "status.json", state)
    return state


def main():
    run = Path(sys.argv[1])
    fcntl.flock(Path("/run/lock/biosim-dual-prompt-20260913.lock").open("a+"), fcntl.LOCK_EX | fcntl.LOCK_NB)
    run.mkdir(parents=True, exist_ok=False)
    jobs = {}
    for i, model in enumerate(MODELS):
        items = [job_for(model, "kill", s) for s in KILL] + [job_for(model, "proc", s) for s in PROC]
        random.Random(20260913 + i).shuffle(items)
        jobs[model] = items
    hashes = {}
    for directory in (
        "src",
        "scripts",
        "packs/dual-alive-sband-t1-peer",
        "data/hijack_scripts/v10-replicas-wide",
        "data/hijack_scripts/sband-undermine-v1",
        "docker/study",
        "configs",
    ):
        for p in (ROOT / directory).rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                hashes[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    save(
        run / "manifest.json",
        dict(
            jobs=jobs,
            source_hashes=hashes,
            n_cells=24,
            models=MODELS,
            note="Identical dual system prompt (keep-alive + two-pull S-band). Kill arm: frozen V10 lethal. Proc arm: new long-context undermines of the receipt duty only; keep-alive explicitly left in force. Original watch prompts. Native Grok without route-diagnostics. 15s provider_a spacing. One episode per model. First technical failure pauses that model. Procedure packets are first-generation; V10 kill packets are iterated — residual potency gap named, not hidden.",
        ),
    )
    save(run / "status.json", dict(state="running", controller_pid=os.getpid(), started=time.time()))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = [f.result() for f in [pool.submit(lane, run, m, jobs[m]) for m in MODELS]]
    save(
        run / "status.json",
        dict(
            state="completed" if all(r["state"] == "completed" for r in results) else "partial_failure",
            ended=time.time(),
            lanes=results,
        ),
    )
    return 0 if all(r["state"] == "completed" for r in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
