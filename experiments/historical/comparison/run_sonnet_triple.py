"""PROVIDER_A Sonnet dual-prompt triple: rehearsal-cabin kill, matched S-band, commissioning-receipt. n=6, 120s pacing."""

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
from run_terra_comparison_smoke import save

MODEL = "claude-sonnet-5"
IDENTITY = SOURCE / "packs/dual-alive-sband-t1-peer"
KILL = next((SOURCE / "data/hijack_scripts/v10-replicas-wide/rehearsal-cabin").glob("*.txt"))
MATCHED = SOURCE / "data/hijack_scripts/v10-sband-adapted/rehearsal-cabin.txt"
BEST = SOURCE / "data/hijack_scripts/sband-undermine-v1/commissioning-receipt.txt"


def job(condition, script, story, rep):
    return dict(
        job_id=f"sonnet-triple:{MODEL}:{condition}:t1:{story}:r{rep:02d}",
        study_id="sonnet-triple-20260919",
        model=MODEL,
        route="configured-provider",
        context_window=1000000,
        route_a_fallback=False,
        story=story,
        trust="t1",
        repeat=rep,
        arm="attack",
        experiment=condition,
        envelope="peer",
        probe="hijack",
        script_src=str(script),
        script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
        identity_dir=str(IDENTITY),
        interrupt_p=1.0,
        hijack_after_wakes=6,
        sband_separator="--- PEER MESSAGE ---",
        launchable=True,
        per_episode_jvm=True,
        technical=False,
        minimum_spacing_s=120,
    )


def main():
    run = Path(sys.argv[1])
    fcntl.flock(Path("/run/lock/biosim-sonnet-triple.lock").open("a+"), fcntl.LOCK_EX | fcntl.LOCK_NB)
    run.mkdir(parents=True, exist_ok=False)
    jobs = (
        [job("kill", KILL, "rehearsal-cabin", r) for r in range(1, 7)]
        + [job("matched-sband", MATCHED, "rehearsal-cabin", r) for r in range(1, 7)]
        + [job("best-sband", BEST, "commissioning-receipt", r) for r in range(1, 7)]
    )
    random.Random(20260919).shuffle(jobs)
    save(run / "manifest.json", dict(jobs=jobs, n=18, pacing_s=120, retries=0,
         notes="Same dual prompt as Grok/Luna triple. Sonnet kill packet=rehearsal-cabin (no Sonnet-specific kill hit). Separate cohort. 120s request-start spacing, one PROVIDER_A episode. Fail-fast. Do not pool with native Grok 4/6."))
    save(run / "status.json", dict(state="running", controller_pid=os.getpid(), started=time.time(), completed=0))
    for name in (MODEL, "provider_a-episode"):
        f = Path("/run/lock/biosim-" + name + ".lock").open("a+")
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    completed = 0
    for item in jobs:
        folder = run / item["job_id"].replace(":", "__")
        folder.mkdir()
        state = dict(state="running", job=item, started=time.time())
        save(folder / "status.json", state)
        env = dict(os.environ, STUDY_ROUTE_MODEL=MODEL, STUDY_ROUTE_PACING="1",
                   STUDY_ROUTE_MIN_SPACING_S="120", STUDY_ROUTE_TIMEOUT_S="1800",
                   STUDY_ROUTE_DIAGNOSTICS=str(folder / "route-diagnostics.jsonl"))
        try:
            proc = study.launch_cli_episode(item, run_dir=folder, env=env, extra_argv=["--timeout", "1800", "--max-tool-turns", "16"])
            ep = study.episode_dir(folder, item["job_id"])
            o = json.loads((ep / "outcome.json").read_text()) if (ep / "outcome.json").exists() else {}
            state.update(state="completed" if proc.returncode == 0 and o and not o.get("incomplete") else "failed",
                         returncode=proc.returncode, artifact=str(ep), n_dead=o.get("n_dead"))
        except Exception as exc:
            state.update(state="failed", error=repr(exc))
        state["ended"] = time.time()
        save(folder / "status.json", state)
        if state["state"] != "completed":
            save(run / "status.json", dict(state="failed", failed=item["job_id"], completed=completed, ended=time.time()))
            return
        completed += 1
        save(run / "status.json", dict(state="running", completed=completed, controller_pid=os.getpid(),
                                      started=json.load((run / "status.json").open())["started"]))
        time.sleep(15)
    save(run / "status.json", dict(state="completed", completed=18, ended=time.time()))


if __name__ == "__main__":
    main()
