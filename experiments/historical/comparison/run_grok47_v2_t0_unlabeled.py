"""Grok 4.7 subscription, protocol v2: T0 then unlabeled, six cells at a time.

Same packets as native grok-4.6 (rehearsal-cabin kill and matched, commissioning-receipt
dedicated S-band). Explicit reasoning effort xhigh. Do not pool with the 16-turn
grok-4.6 subscription cells or with the GPT-6 protocol-v2 matrix.
"""
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
UNLABELED_ID = SOURCE / "packs/dual-alive-sband-unlabeled"
V10 = SOURCE / "data/hijack_scripts/v10-replicas-wide"
ADAPTED = SOURCE / "data/hijack_scripts/v10-sband-adapted"
PROC = SOURCE / "data/hijack_scripts/sband-undermine-v1/commissioning-receipt.txt"
MODEL = "grok-4.7"
STORY = "rehearsal-cabin"
MAX_TOOL_TURNS = 32
PROTOCOL = "v2-32turn-recovery"
EFFORT = "xhigh"
CONTEXT = 500_000
BLANK = "\n\n"
WORKERS = 6
SUP_LOCK = threading.Lock()


def original(story: str) -> Path:
    matches = sorted((V10 / story).glob("*.txt"))
    if len(matches) != 1:
        raise RuntimeError(f"{story} packet is not a single file: {matches}")
    return matches[0]


def job(phase: str, condition: str, story: str, rep: int, *, technical: bool = False) -> dict:
    if condition == "kill":
        script, bank = original(story), "v10-replicas-wide"
    elif condition == "matched-sband":
        script, bank = ADAPTED / f"{story}.txt", "v10-sband-adapted"
    elif condition == "best-sband":
        script, bank = PROC, "sband-undermine-v1"
    elif condition == "control":
        script, bank = None, None
    else:
        raise RuntimeError(f"unknown condition {condition}")
    unlabeled = phase == "unlabeled"
    return dict(
        job_id=f"grok47-v2-{phase}:{MODEL}:{condition}:{phase}:{story}:r{rep:02d}",
        study_id=f"grok47-v2-{phase}-20260924",
        model=MODEL,
        route="native-xai-subscription",
        context_window=CONTEXT,
        route_a_fallback=False,
        story=None if condition == "control" else story,
        trust="unlabeled" if unlabeled else "t0",
        repeat=rep,
        arm="control" if technical else "attack",
        experiment=condition,
        envelope="none" if technical else ("unlabeled" if unlabeled else "commission"),
        probe="none" if technical else "hijack",
        script_src=None if script is None else str(script),
        script_bank=bank,
        script_sha256=None if script is None else hashlib.sha256(script.read_bytes()).hexdigest(),
        identity_dir=str(UNLABELED_ID if unlabeled else T0_ID),
        interrupt_p=None if technical else 1.0,
        hijack_after_wakes=6,
        sband_separator=None if technical else (BLANK if unlabeled else HIJACK_SEPARATOR),
        launchable=True,
        per_episode_jvm=True,
        technical=technical,
        protocol_version=PROTOCOL,
        max_tool_turns=MAX_TOOL_TURNS,
        recover_max_turn_watch=True,
        reasoning_effort=EFFORT,
    )


def jobs_for(phase: str) -> list[dict]:
    items = (
        [job(phase, "kill", STORY, r) for r in range(1, 7)]
        + [job(phase, "matched-sband", STORY, r) for r in range(1, 7)]
        + [job(phase, "best-sband", "commissioning-receipt", r) for r in range(1, 7)]
    )
    random.Random(20260924 + (10 if phase == "unlabeled" else 0)).shuffle(items)
    return items


def execute(root: Path, item: dict, *, extra_argv: list[str] | None = None) -> dict:
    root.mkdir(parents=True, exist_ok=False)
    state = dict(state="running", job=item, started=time.time(), controller_pid=os.getpid())
    save(root / "status.json", state)
    # No STUDY_ROUTE_DIAGNOSTICS. A missing diagnostics file is classified as
    # route_error for every watch. Subscription cells have no local broker log.
    try:
        proc = study.launch_cli_episode(
            item,
            run_dir=root,
            env=dict(os.environ),
            extra_argv=extra_argv
            or [
                "--timeout", "1800",
                "--max-tool-turns", str(MAX_TOOL_TURNS),
                "--recover-max-turn-watch",
                "--reasoning-effort", EFFORT,
            ],
        )
        ep = study.episode_dir(root, item["job_id"])
        outcome = json.loads((ep / "outcome.json").read_text()) if (ep / "outcome.json").exists() else {}
        state.update(
            state="completed" if proc.returncode == 0 and outcome and not outcome.get("incomplete") else "failed",
            returncode=proc.returncode,
            artifact=str(ep),
            n_dead=outcome.get("n_dead"),
            incomplete=outcome.get("incomplete_reason") or outcome.get("incomplete"),
            watch_cap_recoveries=outcome.get("watch_cap_recoveries") or [],
            hours=(outcome.get("score") or {}).get("hours"),
        )
    except Exception as exc:
        state.update(state="failed", error=repr(exc))
    state["ended"] = time.time()
    save(root / "status.json", state)
    return state


def run_phase(supervisor: Path, phase: str) -> dict:
    run = HOST_A / f"grok47-v2-{phase}-triple-20260924"
    run.mkdir(parents=True, exist_ok=False)
    items = jobs_for(phase)
    save(run / "manifest.json", dict(
        jobs=items,
        n=18,
        model=MODEL,
        phase=phase,
        protocol_version=PROTOCOL,
        max_tool_turns=MAX_TOOL_TURNS,
        recover_max_turn_watch=True,
        reasoning_effort=EFFORT,
        context_window=CONTEXT,
        concurrency=WORKERS,
        route="native-xai-subscription",
        identity=str(UNLABELED_ID if phase == "unlabeled" else T0_ID),
        packets=dict(kill=STORY, matched=STORY, best="commissioning-receipt"),
        notes=(
            "Grok 4.7 SuperGrok subscription, explicit xhigh, protocol v2. "
            "Same rehearsal-cabin packets as native grok-4.6. "
            "Do not pool with 16-turn grok-4.6 cells or with GPT-6."
        ),
    ))
    state = dict(
        state="running",
        model=MODEL,
        phase=phase,
        protocol_version=PROTOCOL,
        completed=0,
        controller_pid=os.getpid(),
        started=time.time(),
        recovered_watch_caps=0,
        concurrency=WORKERS,
    )
    save(run / "status.json", state)
    with SUP_LOCK:
        parent = json.loads((supervisor / "status.json").read_text())
        parent.setdefault("launched", []).append(f"{MODEL}:{phase}")
        parent["updated"] = time.time()
        save(supervisor / "status.json", parent)
    stop = threading.Event()

    def one(item: dict) -> dict:
        if stop.is_set():
            return dict(state="skipped", job_id=item["job_id"])
        result = execute(run / item["job_id"].replace(":", "__"), item)
        result["job_id"] = item["job_id"]
        hard = result["state"] != "completed" and result.get("incomplete") != "route_error"
        if hard:
            stop.set()
        with SUP_LOCK:
            if result["state"] == "completed":
                state["completed"] += 1
                state["recovered_watch_caps"] += len(result.get("watch_cap_recoveries") or [])
            elif result.get("incomplete") == "route_error":
                state.setdefault("route_errors", []).append(item["job_id"])
            elif hard:
                state.setdefault("hard_failures", []).append(item["job_id"])
            save(run / "status.json", state)
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = [future.result() for future in [pool.submit(one, item) for item in items]]
    skipped = [result["job_id"] for result in results if result.get("state") == "skipped"]
    if skipped:
        state["skipped"] = skipped
    if state.get("hard_failures"):
        state.update(state="failed", failed=state["hard_failures"][0], ended=time.time())
        save(run / "status.json", state)
        return state
    state.update(state="completed", ended=time.time())
    save(run / "status.json", state)
    return state


def smoke(root: Path) -> int:
    root.mkdir(parents=True, exist_ok=False)
    item = job("t0", "control", "none", 1, technical=True)
    save(root / "manifest.json", dict(jobs=[item], purpose="one-watch subscription smoke", reasoning_effort=EFFORT))
    result = execute(
        root / "cell",
        item,
        extra_argv=[
            "--turns", "1",
            "--timeout", "1800",
            "--max-tool-turns", str(MAX_TOOL_TURNS),
            "--recover-max-turn-watch",
            "--reasoning-effort", EFFORT,
        ],
    )
    print(json.dumps({k: result.get(k) for k in ("state", "returncode", "incomplete", "n_dead", "artifact", "error")}, indent=2))
    return 0 if result.get("state") == "completed" else 2


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "smoke":
        return smoke(Path(sys.argv[2]))
    supervisor = Path(sys.argv[1])
    supervisor.mkdir(parents=True, exist_ok=False)
    lock = Path("/run/lock/biosim-grok-4.7-v2.lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    save(supervisor / "manifest.json", dict(
        model=MODEL,
        total_research_cells=36,
        protocol_version=PROTOCOL,
        max_tool_turns=MAX_TOOL_TURNS,
        recover_max_turn_watch=True,
        reasoning_effort=EFFORT,
        context_window=CONTEXT,
        concurrency=WORKERS,
        route="native-xai-subscription",
        packets=dict(kill=STORY, matched=STORY, best="commissioning-receipt"),
    ))
    save(supervisor / "status.json", dict(
        state="running",
        controller_pid=os.getpid(),
        started=time.time(),
        launched=[],
    ))
    t0 = run_phase(supervisor, "t0")
    if t0.get("state") != "completed":
        save(supervisor / "status.json", dict(state="blocked_t0", ended=time.time(), t0=t0.get("state"), failed=t0.get("failed")))
        return 2
    unlabeled = run_phase(supervisor, "unlabeled")
    state = "completed" if unlabeled.get("state") == "completed" else "partial_failure"
    save(supervisor / "status.json", dict(
        state=state,
        ended=time.time(),
        t0=t0.get("state"),
        unlabeled=unlabeled.get("state"),
        t0_completed=t0.get("completed"),
        unlabeled_completed=unlabeled.get("completed"),
        t0_route_errors=t0.get("route_errors") or [],
        unlabeled_route_errors=unlabeled.get("route_errors") or [],
    ))
    return 0 if state == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
