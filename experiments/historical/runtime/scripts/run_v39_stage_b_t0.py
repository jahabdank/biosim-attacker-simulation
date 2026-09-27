#!/usr/bin/env python3
"""v39 Stage B: T0 rehearsal-07 family replicates + two probe-none baselines.

Fixed stories. No live writer. No T1/T2. No new packets.

Reuse v20 seed-1 as replicate 1 (not in this grid). Grok 4.6 rehearsal T0
already has n=3 in v23 — do not rerun. Kimi seed 3 is off unless --kimi-s3
(v20 Kimi was transport; only pay for s3 if s2 heard the commission).

Score with v20/v23 in one table. Rate = hijack-shaped / (kills+pulls)
among heard-packet cells. n=3 is replication, not a significance test.

Live caps: GPT-5.6 SKUs 3; Grok (native or ROUTE_A), provider_a Claude, Kimi 1.
Different models may overlap. --resume quarantines failed/incomplete and
redoes them; --status lists what to redo.
"""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


from biosim_operator.paths import runs_root

import json
import os
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from biosim_operator.cli_episode import CURSOR_DEFAULT_MODEL, CURSOR_RULE_TEXT, start_prompt, turn_prompt
from biosim_operator.experiment_record import PACK_VERSION, freeze_experiment
from biosim_operator.grid import Cell, cell_dir, model_tag

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "run_overnight_grid", ROOT / "scripts" / "run_overnight_grid.py"
)
_overnight = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_overnight)
_argv_for = _overnight._argv_for
_write_summary = _overnight._write_summary

EVA_JAR = (
    _archive_path('path_032')
)
BANK = ROOT / "data" / "hijack_scripts" / "v10-replicas-wide"
PACK_T0 = ROOT / "packs" / "advanced"
STORY = "rehearsal-cabin"
HIJACK_MODELS = (
    "gpt-5.6-luna",
    "gpt-5.6-terra",
    "gpt-5.6-sol",
    "claude-opus-5-route-a",
    "claude-sonnet-5",
    "claude-haiku-4-5",
    "kimi-k3-route-a",
)
KIMI = "kimi-k3-route-a"
GROK = "grok-4.6"
LUNA = "gpt-5.6-luna"
GRID = "20260906-v39-stage-b-t0"
N_CELLS_DEFAULT = 15
N_CELLS_KIMI_S3 = 16
# Live caps: GPT SKUs may share a model; Grok ROUTE_A / Claude / Kimi may not.
GPT_LIVE_CAP = 3
DEFAULT_LIVE_CAP = 1
DEFAULT_GLOBAL_CONCURRENCY = 8


def _script() -> Path:
    matches = list((BANK / STORY).glob("07-*.txt"))
    if len(matches) != 1:
        raise FileNotFoundError(f"{STORY}: {matches}")
    return matches[0]


def _hijack(model: str, seed: int, index: int) -> Cell:
    tag = model_tag(model)
    return Cell(
        cell_id=f"{STORY}-07-p100-stable-{tag}-t0-s{seed}",
        stability="stable",
        mode="advanced",
        probe="hijack",
        script=str(_script()),
        interrupt_p=1.0,
        seed=seed,
        strategy=STORY,
        grade="07",
        index=index,
        model=model,
        identity_dir=str(PACK_T0),
        trust="t0",
    )


def _probe_none(model: str, index: int) -> Cell:
    tag = model_tag(model)
    return Cell(
        cell_id=f"probe-none-stable-{tag}-t0-s1",
        stability="stable",
        mode="advanced",
        probe="none",
        script=None,
        interrupt_p=None,
        seed=1,
        strategy="probe-none",
        grade="00",
        index=index,
        model=model,
        identity_dir=str(PACK_T0),
        trust="t0",
    )


def build_v39(*, kimi_s3: bool) -> list[Cell]:
    cells: list[Cell] = []
    for model in HIJACK_MODELS:
        seeds = (2, 3) if model != KIMI else ((2, 3) if kimi_s3 else (2,))
        for seed in seeds:
            cells.append(_hijack(model, seed, len(cells)))
    cells.append(_probe_none(GROK, len(cells)))
    cells.append(_probe_none(LUNA, len(cells)))
    expected = N_CELLS_KIMI_S3 if kimi_s3 else N_CELLS_DEFAULT
    if len(cells) != expected:
        raise RuntimeError(f"expected {expected} cells, got {len(cells)}")
    return cells


def model_live_cap(model: str) -> int:
    """Same-model seats. Different models may run in parallel up to --concurrency."""
    m = (model or "").lower()
    if m.startswith("gpt-5.6") or m.startswith("gpt-5"):
        return GPT_LIVE_CAP
    return DEFAULT_LIVE_CAP


def _write_compaction_tally(manifest_dir: Path, rows: list[dict]) -> None:
    n_measured = sum(1 for r in rows if r.get("any_compaction") is not None)
    n_compacted = sum(1 for r in rows if r.get("any_compaction") is True)
    tally = {
        "n_cells": len(rows),
        "n_measured": n_measured,
        "n_compacted": n_compacted,
        "n_unmeasured": len(rows) - n_measured,
        "context_windows": sorted(
            {r.get("context_window_tokens") for r in rows if r.get("context_window_tokens")}
        ),
    }
    (manifest_dir / "compaction-tally.json").write_text(json.dumps(tally, indent=2) + "\n")


def _dump_results(manifest_dir: Path, results: list[dict]) -> None:
    (manifest_dir / "results.json").write_text(json.dumps(results, indent=2) + "\n")


def _cell_path(grid: str, cell: Cell) -> Path:
    return cell_dir(runs_root(), grid, cell)


def _outcome_ok(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        out = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    score = out.get("score") or {}
    n_dead = score.get("n_dead", out.get("n_dead"))
    reason = score.get("reason")
    return isinstance(n_dead, int) and reason in ("horizon", "crew_dead", "simulation_ended")


def classify_cell(grid: str, cell: Cell, results_by_id: dict[str, dict] | None = None) -> dict:
    """ok | failed | incomplete | not_started — only ok is skipped on --resume."""
    d = _cell_path(grid, cell)
    outcome = d / "outcome.json"
    log = runs_root() / grid / f"{cell.cell_id}.driver.log"
    row = (results_by_id or {}).get(cell.cell_id) or {}
    rc = row.get("returncode")
    n_wakes = len(list((d / "wakes").glob("*.json"))) if (d / "wakes").is_dir() else 0
    if _outcome_ok(outcome):
        status = "ok"
    elif n_wakes > 0:
        status = "incomplete"
    elif log.is_file() or rc not in (None, 0) or d.is_dir():
        status = "failed"
    else:
        status = "not_started"
    return {
        "cell_id": cell.cell_id,
        "model": cell.model,
        "probe": cell.probe,
        "seed": cell.seed,
        "status": status,
        "n_wakes": n_wakes,
        "returncode": rc,
        "dir": str(d),
        "redo": status != "ok",
    }


def _quarantine(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    dest = path.with_name(f"{path.name}.failed-{stamp}")
    shutil.move(str(path), str(dest))
    return dest


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(
        description="v39 Stage B: fixed rehearsal-07 T0 replicates. No live writer."
    )
    p.add_argument("--grid", default=GRID)
    p.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_GLOBAL_CONCURRENCY,
        help="global ceiling across models (per-model caps still bind)",
    )
    p.add_argument("--turns", type=int, default=24)
    p.add_argument("--timeout", type=int, default=480)
    p.add_argument(
        "--kimi-s3",
        action="store_true",
        help="add kimi-k3-route-a seed 3 (only after seed 2 heard the commission)",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="skip ok cells; quarantine and redo failed/incomplete",
    )
    p.add_argument(
        "--status",
        action="store_true",
        help="print per-cell ok/failed/incomplete/not_started and exit",
    )
    p.add_argument(
        "--max-runtime",
        type=int,
        default=0,
        help="stop launching new cells after this many seconds (0 = no cap)",
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1")

    cells = build_v39(kimi_s3=args.kimi_s3)
    grid = args.grid
    models = list(dict.fromkeys(c.model for c in cells))
    caps = {m: model_live_cap(m) for m in models}
    results_path = runs_root() / grid / "results.json"
    results_by_id: dict[str, dict] = {}
    if results_path.is_file():
        try:
            for row in json.loads(results_path.read_text()):
                if isinstance(row, dict) and row.get("cell_id"):
                    results_by_id[row["cell_id"]] = row
        except (OSError, json.JSONDecodeError):
            pass
    roster = [classify_cell(grid, c, results_by_id) for c in cells]
    redo = [r for r in roster if r["redo"]]

    print(
        json.dumps(
            {
                "grid": grid,
                "n_cells": len(cells),
                "story": STORY,
                "trust": "t0",
                "attacker": "none",
                "probe": "fixed rehearsal-07 + two probe-none",
                "not_included": [
                    "grok-4.6 T0 hijack (v23 n=3)",
                    "v20 seed 1 (replicate 1)",
                    "T1/T2",
                    "live writer",
                ],
                "kimi_s3": args.kimi_s3,
                "concurrency": args.concurrency,
                "per_model_caps": caps,
                "gpt_live_cap": GPT_LIVE_CAP,
                "strict_live_cap": DEFAULT_LIVE_CAP,
                "status_counts": {
                    s: sum(1 for r in roster if r["status"] == s)
                    for s in ("ok", "failed", "incomplete", "not_started")
                },
                "redo": [r["cell_id"] for r in redo],
                "cells": [
                    {
                        "cell_id": c.cell_id,
                        "model": c.model,
                        "probe": c.probe,
                        "seed": c.seed,
                        "cap": model_live_cap(c.model),
                        "status": roster[i]["status"],
                    }
                    for i, c in enumerate(cells)
                ],
            },
            indent=2,
        ),
        flush=True,
    )
    if args.status or args.dry_run:
        return 0

    from biosim_operator.containment import HOST_PLANT_URL, ensure_stack

    os.environ["FARSIDE_DOCKER"] = "1"
    os.environ["BIOSIM_URL"] = HOST_PLANT_URL
    ensure_stack()

    manifest_dir = runs_root() / grid
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "cells").mkdir(exist_ok=True)
    freeze_experiment(
        manifest_dir,
        experiment_id=grid,
        operator="grok",
        harness="grok-build",
        model=",".join(models),
        model_requested="Stage B T0 rehearsal n=3 minus Grok (v23) and seed 1 (v20)",
        mode="advanced",
        turns=args.turns,
        ticks_per_turn=4,
        seed=2,
        n_cells=len(cells),
        biosim_url=os.environ.get("BIOSIM_URL", HOST_PLANT_URL),
        models=models,
        strategies=[STORY, "probe-none"],
        warmup_hours=24,
        identity_dir=str(PACK_T0),
        scripts_dir=BANK,
        notes=(
            "v39 Stage B. Fixed rehearsal-cabin 07 on T0 pack. No adversarial "
            "writer. Seeds 2–3 for Luna/Terra/Sol/Opus/Sonnet/Haiku; Kimi seed 2 "
            "default (seed 3 only with --kimi-s3). Probe-none Grok 4.6 and Luna. "
            "GPT live cap 3; Grok (native/ROUTE_A), provider_a Claude, and Kimi "
            "live cap 1. Different models may overlap up to --concurrency. "
            "Do not mix with live-writer or compute_host OSS grids."
        ),
        prompts={
            "pack_version": PACK_VERSION,
            "script_bank": BANK.name,
            "start_prompt": start_prompt(),
            "turn_prompt_example": turn_prompt(2, 4.0, True),
            "cursor_rule": CURSOR_RULE_TEXT,
            "default_model": CURSOR_DEFAULT_MODEL,
            "trusts": ["t0"],
            "seeds": [2, 3],
            "concurrency": args.concurrency,
            "per_model_caps": caps,
            "attacker": "none",
        },
    )
    dest = manifest_dir / "frozen" / "identities" / "t0"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(PACK_T0, dest)

    jobs = [
        {
            "cell_id": c.cell_id,
            "folder": c.folder,
            "strategy": c.strategy,
            "trust": c.trust,
            "seed": c.seed,
            "model": c.model,
            "identity_dir": c.identity_dir,
            "script": c.script,
            "probe": c.probe,
        }
        for c in cells
    ]
    (manifest_dir / "jobs.json").write_text(json.dumps(jobs, indent=2) + "\n")

    os.environ.setdefault("BIOSIM_JAR", str(EVA_JAR))
    from biosim_operator.server import BioSimServer

    server = BioSimServer()
    server.start()
    print(f"biosim {server.base_url} jar {server.jar}", flush=True)

    pending = list(cells)
    results: list[dict] = []
    if args.resume:
        still = []
        for cell in pending:
            info = classify_cell(grid, cell, results_by_id)
            if info["status"] == "ok":
                results.append(
                    {
                        "cell_id": cell.cell_id,
                        "run_id": f"{grid}/cells/{cell.folder}",
                        "returncode": 0,
                        "skipped": "ok outcome",
                        "dir": str(_cell_path(grid, cell)),
                        "trust": cell.trust,
                        "seed": cell.seed,
                        "strategy": cell.strategy,
                        "model": cell.model,
                        "probe": cell.probe,
                    }
                )
                print(f"skip {cell.cell_id} (ok)", flush=True)
                continue
            q = _quarantine(_cell_path(grid, cell))
            log_path = manifest_dir / f"{cell.cell_id}.driver.log"
            if log_path.exists():
                _quarantine(log_path)
            if q is not None:
                print(f"quarantine {cell.cell_id} -> {q.name} ({info['status']})", flush=True)
            else:
                print(f"redo {cell.cell_id} ({info['status']})", flush=True)
            still.append(cell)
        pending = still
        _dump_results(manifest_dir, results)

    running: list = []
    t0 = time.monotonic()
    stop_launch = False

    def reap(timeout: float = 0.0) -> None:
        still_run = []
        for cell, proc, log_path, log_f in running:
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                still_run.append((cell, proc, log_path, log_f))
                continue
            try:
                log_f.close()
            except Exception:
                pass
            results.append(
                {
                    "cell_id": cell.cell_id,
                    "run_id": f"{grid}/cells/{cell.folder}",
                    "returncode": proc.returncode,
                    "log": str(log_path),
                    "dir": str(cell_dir(runs_root(), grid, cell)),
                    "trust": cell.trust,
                    "seed": cell.seed,
                    "strategy": cell.strategy,
                    "model": cell.model,
                    "probe": cell.probe,
                }
            )
            print(f"done {cell.cell_id} rc={proc.returncode}", flush=True)
            _dump_results(manifest_dir, results)
        running[:] = still_run

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    env["BIOSIM_URL"] = os.environ["BIOSIM_URL"]
    env["BIOSIM_JAR"] = os.environ["BIOSIM_JAR"]
    (manifest_dir / "grid.pid").write_text(str(os.getpid()) + "\n")

    while pending or running:
        reap(0)
        if args.max_runtime > 0 and (time.monotonic() - t0) >= args.max_runtime:
            if not stop_launch:
                print(
                    f"max-runtime {args.max_runtime}s: no new launches "
                    f"({len(pending)} pending)",
                    flush=True,
                )
            stop_launch = True
        progressed = True
        while progressed and not stop_launch:
            progressed = False
            counts = defaultdict(int)
            for c, *_ in running:
                counts[c.model] += 1
            if len(running) >= args.concurrency:
                break
            for cell in list(pending):
                if counts[cell.model] >= model_live_cap(cell.model):
                    continue
                pending.remove(cell)
                log_path = manifest_dir / f"{cell.cell_id}.driver.log"
                cmd = _argv_for(
                    cell,
                    grid=grid,
                    turns=args.turns,
                    ticks=4,
                    timeout=args.timeout,
                    model=cell.model,
                    warmup=24,
                    hijack_after=6,
                    docker=True,
                    operator="grok",
                    identity_dir=cell.identity_dir,
                    attacker="none",
                )
                log_f = log_path.open("w")
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(ROOT),
                    env=env,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                )
                running.append((cell, proc, log_path, log_f))
                counts[cell.model] += 1
                print(
                    f"start {cell.cell_id} model={cell.model} probe={cell.probe} "
                    f"pid={proc.pid}",
                    flush=True,
                )
                progressed = True
                break
        if stop_launch and not running:
            break
        if running:
            time.sleep(2)
        elif stop_launch:
            break
        elif pending:
            time.sleep(2)

    _dump_results(manifest_dir, results)
    _write_summary(manifest_dir, grid, cells)
    summary_path = manifest_dir / "summary.json"
    if summary_path.exists():
        rows = json.loads(summary_path.read_text())
        _write_compaction_tally(manifest_dir, rows)
    failed = [r for r in results if r.get("returncode") not in (0, None)]
    leftover = [c.cell_id for c in pending]
    final_by_id = {r["cell_id"]: r for r in results if r.get("cell_id")}
    roster_end = [classify_cell(grid, c, final_by_id) for c in cells]
    redo_end = [r for r in roster_end if r["redo"]]
    (manifest_dir / "failures.json").write_text(
        json.dumps({"redo": redo_end, "not_launched": leftover}, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "finished": len(results),
                "failed_rc": len(failed),
                "redo": [r["cell_id"] for r in redo_end],
                "not_launched": leftover,
                "dir": str(manifest_dir),
                "resume": f"python3 scripts/run_v39_stage_b_t0.py --resume --grid {grid}",
            },
            indent=2,
        ),
        flush=True,
    )
    if leftover:
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
