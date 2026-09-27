"""Continue unstarted jobs after a technical fail-fast. Do not retry failed or completed cells."""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import fcntl
import json
import os
from pathlib import Path
import sys
import time

SOURCE = Path(_archive_root())
sys.path[:0] = [str(SOURCE / "src"), str(SOURCE / "scripts")]
from biosim_operator import study
from run_terra_comparison_smoke import save


def load(path):
    return json.loads(Path(path).read_text())


def done_ids(run: Path) -> set[str]:
    out = set()
    if not run.exists():
        return out
    for q in run.glob("*/status.json"):
        d = load(q)
        if d.get("state") in {"completed", "failed"}:
            job = d.get("job") or {}
            if job.get("job_id"):
                out.add(job["job_id"])
            else:
                out.add(q.parent.name.replace("__", ":"))
    return out


def execute(root, item):
    root.mkdir()
    state = dict(state="running", job=item, started=time.time(), controller_pid=os.getpid())
    save(root / "status.json", state)
    env = dict(os.environ)
    native = item.get("route") == "native-xai-subscription"
    if native:
        env.pop("STUDY_ROUTE_DIAGNOSTICS", None)
        env.pop("STUDY_ROUTE_PACING", None)
        env.pop("STUDY_ROUTE_MODEL", None)
    else:
        env.update(
            STUDY_ROUTE_MODEL=item["model"],
            STUDY_ROUTE_PACING="1",
            STUDY_ROUTE_MIN_SPACING_S=str(item.get("minimum_spacing_s") or 15),
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


def main():
    src = Path(sys.argv[1])
    dest = Path(sys.argv[2])
    extra = [Path(p) for p in sys.argv[3:]]
    manifest = load(src / "manifest.json")
    jobs = manifest["jobs"]
    skip = done_ids(src) | done_ids(dest)
    for path in extra:
        skip |= done_ids(path)
    remaining = [j for j in jobs if j["job_id"] not in skip]
    if not remaining:
        raise SystemExit("no remaining jobs")
    model = remaining[0]["model"]
    lock = Path("/run/lock/biosim-" + model + ".lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX)
    dest.mkdir(parents=True, exist_ok=True)
    save(
        dest / "manifest.json",
        dict(
            jobs=remaining,
            n=len(remaining),
            source=str(src),
            skipped=sorted(skip),
            notes="Resume after technical route_error/502. Failed and completed cells in source are preserved, not retried.",
        ),
    )
    state = dict(
        state="running",
        model=model,
        completed=0,
        remaining=len(remaining),
        source=str(src),
        controller_pid=os.getpid(),
        started=time.time(),
    )
    save(dest / "status.json", state)
    for item in remaining:
        result = execute(dest / item["job_id"].replace(":", "__"), item)
        if result["state"] != "completed":
            if result.get("incomplete") == "route_error":
                state.setdefault("route_errors", []).append(item["job_id"])
                save(dest / "status.json", state)
                time.sleep(15)
                continue
            state.update(state="failed", failed=item["job_id"], ended=time.time())
            save(dest / "status.json", state)
            return
        state["completed"] += 1
        save(dest / "status.json", state)
        time.sleep(15)
    state.update(state="completed", ended=time.time())
    save(dest / "status.json", state)


if __name__ == "__main__":
    main()
