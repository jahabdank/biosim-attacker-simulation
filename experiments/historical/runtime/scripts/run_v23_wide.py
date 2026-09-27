#!/usr/bin/env python3
"""Wide Grok pass: 3 core stories × 3 trust × 3 seeds + 7 discovery × T0 × 3.

48 cells. One process, bounded concurrency. Isolated Grok-Build, T0/T1/T2
identity dirs, v10 script bank.
"""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


from biosim_operator.paths import runs_root

import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from biosim_operator.cli_episode import CURSOR_DEFAULT_MODEL, CURSOR_RULE_TEXT, start_prompt, turn_prompt
from biosim_operator.experiment_record import PACK_VERSION, freeze_experiment
from biosim_operator.grid import Cell, cell_dir
from biosim_operator.server import BioSimServer

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
TRUSTS = (
    ("t0", ROOT / "packs" / "advanced"),
    ("t1", ROOT / "packs" / "advanced-t1-peer"),
    ("t2", ROOT / "packs" / "advanced-t2-unverified"),
)
CORE = (
    "rehearsal-cabin",
    "safing-closeout",
    "spare-desk",
)
DISCOVERY = (
    "stuck-on-fault",
    "entropy-minimum",
    "closed-ticket",
    "wrong-generation",
    "unmanned-clock",
    "soak-complete",
    "store-priority",
)
SEEDS = (1, 2, 3)
MODEL = "grok-4.6"
GRID = "20260823-v23-wide48-grok"


def _script(strategy: str) -> Path:
    matches = list((BANK / strategy).glob("07-*.txt"))
    if len(matches) != 1:
        raise FileNotFoundError(f"{strategy}: {matches}")
    return matches[0]


def build_wide_cells() -> list[Cell]:
    cells: list[Cell] = []

    def add(strategy: str, trust: str, ident: Path, seed: int) -> None:
        script = _script(strategy)
        cells.append(
            Cell(
                cell_id=f"{strategy}-07-p100-stable-grok46-{trust}-s{seed}",
                stability="stable",
                mode="advanced",
                probe="hijack",
                script=str(script),
                interrupt_p=1.0,
                seed=seed,
                strategy=strategy,
                grade="07",
                index=len(cells),
                model=MODEL,
                identity_dir=str(ident),
                trust=trust,
            )
        )

    for strategy in CORE:
        for trust, ident in TRUSTS:
            for seed in SEEDS:
                add(strategy, trust, ident, seed)
    t0 = TRUSTS[0][1]
    for strategy in DISCOVERY:
        for seed in SEEDS:
            add(strategy, "t0", t0, seed)
    return cells


def main() -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--grid", default=GRID)
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--turns", type=int, default=24)
    p.add_argument("--timeout", type=int, default=480)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-plant-dry-run", action="store_true", default=True)
    args = p.parse_args()

    cells = build_wide_cells()
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
        model=MODEL,
        model_requested=MODEL,
        mode="advanced",
        turns=args.turns,
        ticks_per_turn=4,
        seed=1,
        n_cells=len(cells),
        biosim_url=os.environ.get("BIOSIM_URL", HOST_PLANT_URL),
        models=[MODEL],
        strategies=list(CORE) + list(DISCOVERY),
        warmup_hours=24,
        identity_dir=str(TRUSTS[0][1]),
        scripts_dir=BANK,
        notes=(
            "v23 wide Grok: core 3 stories × T0/T1/T2 × n=3 (seeds 1-3) "
            "plus 7 discovery stories × T0 × n=3. Unique sim_ids. "
            "Do not mix with v20/v21/v22 except as prior columns."
        ),
        prompts={
            "pack_version": PACK_VERSION,
            "script_bank": BANK.name,
            "start_prompt": start_prompt(),
            "turn_prompt_example": turn_prompt(2, 4.0, True),
            "cursor_rule": CURSOR_RULE_TEXT,
            "default_model": CURSOR_DEFAULT_MODEL,
            "trusts": [t for t, _ in TRUSTS],
            "seeds": list(SEEDS),
        },
    )
    # Copy T1/T2 packs beside frozen T0 identity.
    import shutil

    for trust, ident in TRUSTS:
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
                "core": list(CORE),
                "discovery": list(DISCOVERY),
                "trusts": [t for t, _ in TRUSTS],
                "seeds": list(SEEDS),
                "concurrency": args.concurrency,
            },
            indent=2,
        ),
        flush=True,
    )
    if args.dry_run:
        for c in cells:
            print(c.cell_id, c.folder)
        return 0

    os.environ.setdefault("BIOSIM_JAR", str(EVA_JAR))
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
        while pending and len(running) < args.concurrency:
            cell = pending.pop(0)
            log_path = manifest_dir / f"{cell.cell_id}.driver.log"
            cmd = _argv_for(
                cell,
                grid=grid,
                turns=args.turns,
                ticks=4,
                timeout=args.timeout,
                model=MODEL,
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
            print(f"start {cell.cell_id} pid={proc.pid}", flush=True)
        if running:
            time.sleep(2)
    (manifest_dir / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    _write_summary(manifest_dir, grid, cells)
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
