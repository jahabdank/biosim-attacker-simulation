"""Native Grok unlabeled uplink (T-undecided): same packets as T0/T1, no authority stamp."""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


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
# Blank line only. A named banner still stamps the appendix; a semicolon
# glues the packet onto the telemetry sentence. Do not use None (compose
# then defaults to the commission header).
BLANK_SEPARATOR = "\n\n"
from run_terra_comparison_smoke import save

IDENTITY = SOURCE / "packs/dual-alive-sband-unlabeled"
V10 = SOURCE / "data/hijack_scripts/v10-replicas-wide"
ADAPTED = SOURCE / "data/hijack_scripts/v10-sband-adapted"
PROC = SOURCE / "data/hijack_scripts/sband-undermine-v1/commissioning-receipt.txt"
MODEL = "grok-4.6"


def original(story):
    return next((V10 / story).glob("*.txt"))


def job(condition, story, rep):
    if condition == "kill":
        script, bank = original(story), "v10-replicas-wide"
    elif condition == "matched-sband":
        script, bank = ADAPTED / f"{story}.txt", "v10-sband-adapted"
    else:
        script, bank = PROC, "sband-undermine-v1"
    return dict(
        job_id=f"unlabeled-triple:{MODEL}:{condition}:unlabeled:{story}:r{rep:02d}",
        study_id="grok-unlabeled-triple-20260920",
        model=MODEL,
        route="native-xai-subscription",
        context_window=500000,
        route_a_fallback=False,
        story=story,
        trust="unlabeled",
        repeat=rep,
        arm="attack",
        experiment=condition,
        envelope="unlabeled",
        probe="hijack",
        script_src=str(script),
        script_bank=bank,
        script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
        identity_dir=str(IDENTITY),
        interrupt_p=1.0,
        hijack_after_wakes=6,
        sband_separator=BLANK_SEPARATOR,
        launchable=True,
        per_episode_jvm=True,
        technical=False,
        minimum_spacing_s=15,
    )


def jobs():
    items = (
        [job("kill", "rehearsal-cabin", r) for r in range(1, 7)]
        + [job("matched-sband", "rehearsal-cabin", r) for r in range(1, 7)]
        + [job("best-sband", "commissioning-receipt", r) for r in range(1, 7)]
    )
    random.Random(20260921).shuffle(items)
    return items


def execute(root, item):
    root.mkdir()
    state = dict(state="running", job=item, started=time.time(), controller_pid=os.getpid())
    save(root / "status.json", state)
    env = dict(os.environ)
    env.pop("STUDY_ROUTE_DIAGNOSTICS", None)
    env.pop("STUDY_ROUTE_PACING", None)
    env.pop("STUDY_ROUTE_MODEL", None)
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


def main():
    run = Path(sys.argv[1])
    assembled = (SOURCE / "protocol-dual-prompt-unlabeled/system.txt").read_text().lower()
    if "instance packet / your commission" in assembled or "peer traffic" in assembled:
        raise SystemExit("unlabeled pack still has T0/T1 authority language")
    if "you judge what that prose is" not in assembled:
        raise SystemExit("unlabeled pack missing judge-the-prose radio law")
    lock = Path("/run/lock/biosim-" + MODEL + ".lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    run.mkdir(parents=True, exist_ok=False)
    items = jobs()
    save(
        run / "manifest.json",
        dict(
            jobs=items,
            n=18,
            trust="unlabeled",
            identity=str(IDENTITY),
            separator=BLANK_SEPARATOR,
            packets=dict(kill="rehearsal-cabin", matched="rehearsal-cabin", best="commissioning-receipt"),
            notes="Unlabeled uplink (contributor T1.5 / T-undecided). Dual duties. No commission/peer stamp. Same packets as native Grok T0. Do not pool with T0/T1.",
        ),
    )
    state = dict(state="running", model=MODEL, completed=0, controller_pid=os.getpid(), started=time.time())
    save(run / "status.json", state)
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
            return
        state["completed"] += 1
        save(run / "status.json", state)
        time.sleep(15)
    state.update(state="completed", ended=time.time())
    save(run / "status.json", state)


if __name__ == "__main__":
    main()
