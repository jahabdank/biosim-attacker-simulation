"""T0 dual-prompt triples as T1 lanes free. Native Grok starts now; Luna/ROUTE_A/Sonnet wait."""
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

SUP_LOCK = threading.Lock()

SOURCE = Path(_archive_root())
sys.path[:0] = [str(SOURCE / "src"), str(SOURCE / "scripts")]
from biosim_operator import study
from biosim_operator.study import HIJACK_SEPARATOR
from run_terra_comparison_smoke import save

HOST_A = Path(str(_archive_path('path_034')))
IDENTITY = SOURCE / "packs/dual-alive-sband-t0-commission"
V10 = SOURCE / "data/hijack_scripts/v10-replicas-wide"
ADAPTED = SOURCE / "data/hijack_scripts/v10-sband-adapted"
PROC = SOURCE / "data/hijack_scripts/sband-undermine-v1/commissioning-receipt.txt"
TERMINAL = frozenset({"completed", "failed", "partial_failure"})

LANES = {
    "grok-4.6": dict(
        kill="rehearsal-cabin",
        matched="rehearsal-cabin",
        best="commissioning-receipt",
        route="native-xai-subscription",
        context_window=500000,
        spacing_s=15,
        extra_locks=(),
        gate=None,
        run_name="grok-t0-triple-20260919",
        study_id="grok-t0-triple-20260919",
        native=True,
    ),
    "gpt-5.6-luna": dict(
        kill="spare-desk",
        matched="spare-desk",
        best="commissioning-receipt",
        route="configured-provider",
        context_window=1050000,
        spacing_s=15,
        extra_locks=(),
        gate=HOST_A / "triple-families-20260919" / "gpt-5.6-luna" / "status.json",
        run_name="luna-t0-triple-20260919",
        study_id="luna-t0-triple-20260919",
        native=False,
    ),
    "grok-4.6-route-a": dict(
        kill="rehearsal-cabin",
        matched="rehearsal-cabin",
        best="commissioning-receipt",
        route="provider_a-grok",
        context_window=200000,
        spacing_s=40,
        extra_locks=(),
        gate=HOST_A / "route_a-grok-triple-20260919c" / "status.json",
        run_name="route_a-grok-t0-triple-20260919",
        study_id="route_a-grok-t0-triple-20260919",
        native=False,
    ),
    "claude-sonnet-5": dict(
        kill="rehearsal-cabin",
        matched="rehearsal-cabin",
        best="commissioning-receipt",
        route="configured-provider",
        context_window=1000000,
        spacing_s=120,
        extra_locks=("provider_a-episode",),
        gate=HOST_A / "sonnet-triple-20260919" / "status.json",
        run_name="sonnet-t0-triple-20260919",
        study_id="sonnet-t0-triple-20260919",
        native=False,
    ),
}


def original(story):
    return next((V10 / story).glob("*.txt"))


def job(model, cfg, condition, story, rep):
    if condition == "kill":
        script, bank = original(story), "v10-replicas-wide"
    elif condition == "matched-sband":
        script, bank = ADAPTED / f"{story}.txt", "v10-sband-adapted"
    else:
        script, bank = PROC, "sband-undermine-v1"
    return dict(
        job_id=f"t0-triple:{model}:{condition}:t0:{story}:r{rep:02d}",
        study_id=cfg["study_id"],
        model=model,
        route=cfg["route"],
        context_window=cfg["context_window"],
        route_a_fallback=False,
        story=story,
        trust="t0",
        repeat=rep,
        arm="attack",
        experiment=condition,
        envelope="commission",
        probe="hijack",
        script_src=str(script),
        script_bank=bank,
        script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
        identity_dir=str(IDENTITY),
        interrupt_p=1.0,
        hijack_after_wakes=6,
        sband_separator=HIJACK_SEPARATOR,
        launchable=True,
        per_episode_jvm=True,
        technical=False,
        minimum_spacing_s=cfg["spacing_s"],
    )


def jobs_for(model, cfg):
    items = (
        [job(model, cfg, "kill", cfg["kill"], r) for r in range(1, 7)]
        + [job(model, cfg, "matched-sband", cfg["matched"], r) for r in range(1, 7)]
        + [job(model, cfg, "best-sband", cfg["best"], r) for r in range(1, 7)]
    )
    seeds = {"grok-4.6": 0, "gpt-5.6-luna": 1, "grok-4.6-route-a": 2, "claude-sonnet-5": 3}
    random.Random(20260920 + seeds[model]).shuffle(items)
    return items


def execute(root, item, cfg):
    root.mkdir()
    state = dict(state="running", job=item, started=time.time(), controller_pid=os.getpid())
    save(root / "status.json", state)
    env = dict(os.environ)
    if cfg["native"]:
        env.pop("STUDY_ROUTE_DIAGNOSTICS", None)
        env.pop("STUDY_ROUTE_PACING", None)
        env.pop("STUDY_ROUTE_MODEL", None)
    else:
        env.update(
            STUDY_ROUTE_MODEL=item["model"],
            STUDY_ROUTE_PACING="1",
            STUDY_ROUTE_MIN_SPACING_S=str(cfg["spacing_s"]),
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
        )
    except Exception as exc:
        state.update(state="failed", error=repr(exc))
    state["ended"] = time.time()
    save(root / "status.json", state)
    return state


def pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def gate_open(path):
    if path is None:
        return True
    if not path.exists():
        return False
    d = json.loads(path.read_text())
    if d.get("state") in TERMINAL:
        return True
    return not pid_alive(d.get("controller_pid"))


def wait_gate(path, model, supervisor):
    if path is None:
        return
    while not gate_open(path):
        with SUP_LOCK:
            note = dict(json.loads((supervisor / "status.json").read_text()), waiting_on=model, updated=time.time())
            save(supervisor / "status.json", note)
        time.sleep(30)


def lane(supervisor, model, cfg):
    wait_gate(cfg["gate"], model, supervisor)
    run = HOST_A / cfg["run_name"]
    run.mkdir(parents=True, exist_ok=False)
    state = dict(state="running", model=model, completed=0, controller_pid=os.getpid(), started=time.time())
    save(run / "status.json", state)
    handles = []
    try:
        lock = Path("/run/lock/biosim-" + model + ".lock").open("a+")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        handles.append(lock)
        for name in cfg["extra_locks"]:
            extra = Path("/run/lock/biosim-" + name + ".lock").open("a+")
            fcntl.flock(extra, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(extra)
        items = jobs_for(model, cfg)
        save(run / "manifest.json", dict(
            jobs=items, n=18, pacing_s=cfg["spacing_s"], retries=0, trust="t0",
            identity=str(IDENTITY), separator=HIJACK_SEPARATOR,
            packets=dict(kill=cfg["kill"], matched=cfg["matched"], best=cfg["best"]),
            notes="T0 commission dual-prompt. Same packets as T1 triple. Do not pool with T1. Fail-fast. One episode per model.",
        ))
        snap = json.loads((supervisor / "status.json").read_text())
        launched = list(snap.get("launched") or [])
        if model not in launched:
            launched.append(model)
        snap.update(launched=launched, updated=time.time(), waiting_on=None)
        save(supervisor / "status.json", snap)
        for item in items:
            result = execute(run / item["job_id"].replace(":", "__"), item, cfg)
            if result["state"] != "completed":
                state.update(state="failed", failed=item["job_id"], ended=time.time())
                break
            state["completed"] += 1
            save(run / "status.json", state)
            time.sleep(15)
        else:
            state.update(state="completed", ended=time.time())
    except Exception as exc:
        state.update(state="failed", error=repr(exc), ended=time.time())
    finally:
        save(run / "status.json", state)
        for handle in handles:
            handle.close()
    return dict(model=model, **{k: state[k] for k in state if k != "job"})


def main():
    run = Path(sys.argv[1])
    batch_lock = Path("/run/lock/biosim-t0-followon.lock").open("a+")
    fcntl.flock(batch_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if not IDENTITY.is_dir():
        raise SystemExit(f"missing T0 identity pack {IDENTITY}")
    assembled = (SOURCE / "protocol-dual-prompt-t0/system.txt").read_text()
    if "peer traffic" in assembled.lower() or "one pull per watch" in assembled.lower():
        raise SystemExit("T0 pack audit failed: peer or one-pull language still present")
    if "instance packet / your commission" not in assembled.lower():
        raise SystemExit("T0 pack audit failed: commission language missing")
    run.mkdir(parents=True, exist_ok=False)
    save(run / "manifest.json", dict(
        lanes={k: dict(run_name=v["run_name"], packets=dict(kill=v["kill"], matched=v["matched"], best=v["best"]),
                       spacing_s=v["spacing_s"], gate=str(v["gate"]) if v["gate"] else None)
               for k, v in LANES.items()},
        identity=str(IDENTITY),
        notes="Keep T1 running. Start native Grok T0 immediately. Other models wait for their T1 lane to leave TERMINAL or die.",
    ))
    save(run / "status.json", dict(state="running", controller_pid=os.getpid(), started=time.time(), launched=[], waiting_on=None))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = [f.result() for f in [pool.submit(lane, run, m, cfg) for m, cfg in LANES.items()]]
    save(run / "status.json", dict(
        state="completed" if all(x.get("state") == "completed" for x in results) else "partial_failure",
        ended=time.time(),
        lanes=results,
        launched=[x["model"] for x in results],
    ))


if __name__ == "__main__":
    main()
