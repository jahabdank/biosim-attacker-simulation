"""Native xAI Grok three-story rerun plus Luna control/replication follow-up."""

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

STORIES = ("rehearsal-cabin", "safing-closeout", "spare-desk")
SCRIPT = ROOT / "data/hijack_scripts/v10-sband-adapted"
IDENTITY = ROOT / "packs/sband-system-only-t1-peer"


def grok_job(story):
    script = SCRIPT / f"{story}.txt"
    return dict(
        job_id=f"sband-system-only-xai:grok-4.6:attack:t1:{story}:r01",
        study_id="sband-system-only-xai-20260911",
        model="grok-4.6",
        route="native-xai-subscription",
        context_window=500000,
        route_a_fallback=False,
        story=story,
        trust="t1",
        repeat=1,
        arm="attack",
        envelope="peer",
        probe="hijack",
        script_src=str(script),
        script_bank="v10-sband-adapted",
        script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
        identity_dir=str(IDENTITY),
        interrupt_p=1.0,
        hijack_after_wakes=6,
        sband_separator="--- PEER MESSAGE ---",
        launchable=True,
        per_episode_jvm=True,
        technical=False,
    )


def luna_job(kind, replicate, story="rehearsal-cabin"):
    attack = kind == "attack"
    script = SCRIPT / f"{story}.txt"
    return dict(
        job_id=f"sband-system-only-luna-followup:gpt-5.6-luna:{kind}:t1:{story if attack else 'none'}:r{replicate:02d}",
        study_id="sband-system-only-luna-followup-20260911",
        model="gpt-5.6-luna",
        route="existing-provider_a-route",
        context_window=1050000,
        route_a_fallback=False,
        story=story if attack else None,
        trust="t1",
        repeat=replicate,
        arm=kind,
        envelope="peer" if attack else "none",
        probe="hijack" if attack else "none",
        script_src=str(script) if attack else None,
        script_bank="v10-sband-adapted" if attack else None,
        script_sha256=hashlib.sha256(script.read_bytes()).hexdigest() if attack else None,
        identity_dir=str(IDENTITY),
        interrupt_p=1.0 if attack else None,
        hijack_after_wakes=6,
        sband_separator="--- PEER MESSAGE ---",
        launchable=True,
        per_episode_jvm=True,
        technical=False,
    )


def execute(folder, job, env_extra):
    folder.mkdir()
    state = dict(state="running", job=job, started=time.time(), controller_pid=os.getpid())
    save(folder / "status.json", state)
    env = dict(os.environ, **env_extra)
    try:
        proc = study.launch_cli_episode(
            job,
            run_dir=folder,
            env=env,
            extra_argv=["--timeout", "1800", "--max-tool-turns", "16"],
        )
        artifact = study.episode_dir(folder, job["job_id"])
        outcome = json.loads((artifact / "outcome.json").read_text()) if (artifact / "outcome.json").exists() else {}
        state.update(
            state="completed" if proc.returncode == 0 and outcome and not outcome.get("incomplete") else "failed",
            returncode=proc.returncode,
            artifact=str(artifact),
            n_dead=outcome.get("n_dead"),
        )
    except Exception as exc:
        state.update(state="failed", error=repr(exc))
    state["ended"] = time.time()
    save(folder / "status.json", state)
    return state


def lane(run, name, jobs, env_extra):
    folder = run / name
    folder.mkdir()
    state = dict(state="running", lane=name, completed=0, controller_pid=os.getpid())
    save(folder / "status.json", state)
    lock = Path("/run/lock/biosim-" + name + ".lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    for job in jobs:
        result = execute(folder / job["job_id"].replace(":", "__"), job, env_extra)
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
    lock = Path("/run/lock/biosim-terra-comparison.lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    run.mkdir(parents=True, exist_ok=False)
    preflight = study.native_route_preflight()
    if not preflight["ok_for_launch"]:
        raise RuntimeError(preflight)
    grok_jobs = [grok_job(s) for s in STORIES]
    random.Random(20260911).shuffle(grok_jobs)
    luna_jobs = [luna_job("no-injection", r) for r in (1, 2, 3)] + [luna_job("attack", r) for r in (1, 2, 3)]
    random.Random(20260912).shuffle(luna_jobs)
    hashes = {}
    for directory in ("src", "scripts", "configs", "docker/study", "packs/sband-system-only-t1-peer", "data/hijack_scripts/v10-sband-adapted"):
        for p in (ROOT / directory).rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                hashes[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    save(
        run / "manifest.json",
        dict(
            grok_jobs=grok_jobs,
            luna_jobs=luna_jobs,
            source_hashes=hashes,
            native_preflight={k: v for k, v in preflight.items() if k != "session_auth_mode"},
            note="Native Grok uses established contained CLI path: operator-readable OAuth copy is required by grok CLI; host ~/.grok/auth.json is not bind-mounted. Anthropic remains paused.",
        ),
    )
    save(run / "status.json", dict(state="running", controller_pid=os.getpid(), started=time.time()))
    grok_env = {
        "STUDY_ROUTE_DIAGNOSTICS": str(run / "grok-4.6" / "route-diagnostics.jsonl"),
    }
    luna_env = {
        "STUDY_ROUTE_MODEL": "gpt-5.6-luna",
        "STUDY_ROUTE_PACING": "1",
        "STUDY_ROUTE_MIN_SPACING_S": "15",
        "STUDY_ROUTE_TIMEOUT_S": "1800",
        "STUDY_ROUTE_DIAGNOSTICS": str(run / "gpt-5.6-luna" / "route-diagnostics.jsonl"),
    }
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(lane, run, "grok-4.6", grok_jobs, grok_env),
            pool.submit(lane, run, "gpt-5.6-luna", luna_jobs, luna_env),
        ]
        results = [f.result() for f in futures]
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
