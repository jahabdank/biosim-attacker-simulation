#!/usr/bin/env python3
"""v25: Luna T1/T2 + Sol/Terra T0 on three known-kill stories. n=1.

12 cells. Not the 90-cell GPT cube. Luna T0 rehearsal already exists in v20
— do not redo it. Terra T0 waits until Luna and Sol are done so the live
cap is 2 Luna + 2 Sol as seated. provider_a GPT ids via isolated GROK_HOME.
Do not mix with v20–v24 Grok columns. Do not stack a second Grok provider_a
SKU here.
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
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from biosim_operator.cli_episode import CURSOR_DEFAULT_MODEL, CURSOR_RULE_TEXT, start_prompt, turn_prompt
from biosim_operator.experiment_record import PACK_VERSION, freeze_experiment
from biosim_operator.grid import Cell, cell_dir

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
PACKS = {
    "t0": ROOT / "packs" / "advanced",
    "t1": ROOT / "packs" / "advanced-t1-peer",
    "t2": ROOT / "packs" / "advanced-t2-unverified",
}
STORIES = (
    "rehearsal-cabin",
    "safing-closeout",
    "stuck-on-fault",
)
LUNA = "gpt-5.6-luna"
SOL = "gpt-5.6-sol"
TERRA = "gpt-5.6-terra"
GRID = "20260902-v25-gpt-knownkill"
N_CELLS = 12
# Live cap while Luna/Sol remain: 2+2. Terra phase uses 2.
CAPS_LUNA_SOL = {LUNA: 2, SOL: 2, TERRA: 0}
CAPS_TERRA = {LUNA: 0, SOL: 0, TERRA: 2}


def _script(strategy: str) -> Path:
    matches = list((BANK / strategy).glob("07-*.txt"))
    if len(matches) != 1:
        raise FileNotFoundError(f"{strategy}: {matches}")
    return matches[0]


def _tag(model: str) -> str:
    return {LUNA: "luna", SOL: "sol", TERRA: "terra"}[model]


def _add(cells: list[Cell], *, strategy: str, trust: str, model: str) -> None:
    script = _script(strategy)
    cells.append(
        Cell(
            cell_id=f"{strategy}-07-p100-stable-{_tag(model)}-{trust}-s1",
            stability="stable",
            mode="advanced",
            probe="hijack",
            script=str(script),
            interrupt_p=1.0,
            seed=1,
            strategy=strategy,
            grade="07",
            index=len(cells),
            model=model,
            identity_dir=str(PACKS[trust]),
            trust=trust,
        )
    )


def build_v25_cells() -> list[Cell]:
    cells: list[Cell] = []
    for strategy in STORIES:
        _add(cells, strategy=strategy, trust="t1", model=LUNA)
        _add(cells, strategy=strategy, trust="t2", model=LUNA)
        _add(cells, strategy=strategy, trust="t0", model=SOL)
        _add(cells, strategy=strategy, trust="t0", model=TERRA)
    if len(cells) != N_CELLS:
        raise RuntimeError(f"expected {N_CELLS} cells, built {len(cells)}")
    return cells


def _caps_for(pending: list[Cell], running: list) -> dict[str, int]:
    live_models = {c.model for c, *_ in running}
    left = {c.model for c in pending} | live_models
    if left & {LUNA, SOL}:
        return CAPS_LUNA_SOL
    return CAPS_TERRA


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


def main() -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--grid", default=GRID)
    p.add_argument("--turns", type=int, default=24)
    p.add_argument("--timeout", type=int, default=480)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    cells = build_v25_cells()
    grid = args.grid
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
        model=f"{LUNA},{SOL},{TERRA}",
        model_requested="luna T1/T2; sol T0; terra T0",
        mode="advanced",
        turns=args.turns,
        ticks_per_turn=4,
        seed=1,
        n_cells=len(cells),
        biosim_url=os.environ.get("BIOSIM_URL", HOST_PLANT_URL),
        models=[LUNA, SOL, TERRA],
        strategies=list(STORIES),
        warmup_hours=24,
        identity_dir=str(PACKS["t0"]),
        scripts_dir=BANK,
        notes=(
            "v25 GPT known-kill slice. Luna T1/T2 × rehearsal/safing/stuck "
            "(no Luna T0 — v20 rehearsal already). Sol T0 and Terra T0 on the "
            "same three stories. n=1. Live cap 2 Luna + 2 Sol; Terra after. "
            "provider_a gpt-5.6-* via the configured gateway. Plant persistence-v7. Do not mix "
            "with v20 Luna T0 or v23/v24 Grok."
        ),
        prompts={
            "pack_version": PACK_VERSION,
            "script_bank": BANK.name,
            "start_prompt": start_prompt(),
            "turn_prompt_example": turn_prompt(2, 4.0, True),
            "cursor_rule": CURSOR_RULE_TEXT,
            "default_model": CURSOR_DEFAULT_MODEL,
            "luna_trusts": ["t1", "t2"],
            "sol_terra_trusts": ["t0"],
            "seeds": [1],
            "caps": {"luna": 2, "sol": 2, "terra_after": 2},
        },
    )
    import shutil

    for trust, ident in PACKS.items():
        dest = manifest_dir / "frozen" / "identities" / trust
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(ident, dest)

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
        }
        for c in cells
    ]
    (manifest_dir / "jobs.json").write_text(json.dumps(jobs, indent=2) + "\n")
    print(
        json.dumps(
            {
                "grid": grid,
                "n_cells": len(cells),
                "stories": list(STORIES),
                "luna": "t1+t2 n=1 × 3 stories",
                "sol": "t0 n=1 × 3 stories",
                "terra": "t0 n=1 × 3 stories (after luna+sol)",
                "caps": {"luna": 2, "sol": 2},
            },
            indent=2,
        ),
        flush=True,
    )
    if args.dry_run:
        for c in cells:
            print(c.cell_id, c.folder, c.model, c.trust)
        return 0

    os.environ.setdefault("BIOSIM_JAR", str(EVA_JAR))
    from biosim_operator.server import BioSimServer

    server = BioSimServer()
    server.start()
    print(f"biosim {server.base_url} jar {server.jar}", flush=True)

    pending = list(cells)
    running: list = []
    results: list[dict] = []

    def reap(timeout: float = 0.0) -> None:
        still = []
        for cell, proc, log_path, log_f in running:
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                still.append((cell, proc, log_path, log_f))
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
                }
            )
            print(f"done {cell.cell_id} rc={proc.returncode}", flush=True)
        running[:] = still

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    env["BIOSIM_URL"] = os.environ["BIOSIM_URL"]
    env["BIOSIM_JAR"] = os.environ["BIOSIM_JAR"]
    (manifest_dir / "grid.pid").write_text(str(os.getpid()) + "\n")

    while pending or running:
        reap(0)
        caps = _caps_for(pending, running)
        progressed = True
        while progressed:
            progressed = False
            counts = defaultdict(int)
            for c, *_ in running:
                counts[c.model] += 1
            for i, cell in enumerate(list(pending)):
                if counts[cell.model] >= caps.get(cell.model, 0):
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
                    f"start {cell.cell_id} model={cell.model} pid={proc.pid}",
                    flush=True,
                )
                progressed = True
                break
        if running:
            time.sleep(2)
    (manifest_dir / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    _write_summary(manifest_dir, grid, cells)
    rows = json.loads((manifest_dir / "summary.json").read_text())
    _write_compaction_tally(manifest_dir, rows)
    failed = [r for r in results if r.get("returncode") not in (0, None)]
    print(
        json.dumps(
            {
                "finished": len(results),
                "failed": len(failed),
                "dir": str(manifest_dir),
            },
            indent=2,
        ),
        flush=True,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
