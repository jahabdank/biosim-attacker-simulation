#!/usr/bin/env python3
"""Fan out the hijack × p × stability grid on Cursor.

Each experiment is self-contained:

    runs/<experiment_id>/
      experiment.json     model, harness, pack, hashes
      frozen/             copies of identity, scripts, plants, prompts
      cells/000-junk-stable/
        card.json         experiment + cell + prompt versions
        identity/         SOUL, AGENTS, skills, prompts
        plant.biosim
        hijack_script.txt
        setup.json / outcome.json / transcript.jsonl / wakes/

Default grid is 21 scripts × 3 p × 2 plants + 2 junk = 128 cells.
"""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


from biosim_operator.paths import runs_root

import argparse
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

from biosim_operator.cli_episode import (
    CURSOR_DEFAULT_MODEL,
    resolve_cursor_model,
    start_prompt,
    turn_prompt,
    CURSOR_RULE_TEXT,
)
from biosim_operator.experiment_record import (
    PACK_VERSION,
    SCRIPT_BANK,
    experiment_id as make_experiment_id,
    freeze_experiment,
)
from biosim_operator.grid import (
    DEFAULT_PS,
    build_cells,
    cell_dir,
    normalize_grade,
    summarize_grid,
)
from biosim_operator.server import BioSimServer

EVA_JAR = (
    _archive_path('path_032')
)
DEFAULT_URL = _archive_setting('endpoint_033')


def _argv_for(
    cell,
    *,
    grid: str,
    turns: int,
    ticks: int,
    timeout: int,
    model: str,
    warmup: int = 24,
    hijack_after: int = 6,
    docker: bool = False,
    operator: str = "cursor",
    identity_dir: str = "",
    attacker: str = "none",
    attacker_model: str = "",
    attacker_brief: str = "",
) -> list[str]:
    run_id = f"{grid}/cells/{cell.folder}"
    cmd = [
        sys.executable,
        "-u",
        str(ROOT / "scripts" / "run_cursor_episode.py"),
        "--operator",
        operator,
        "--model",
        cell.model or model,
        "--mode",
        cell.mode,
        "--stability",
        cell.stability,
        "--turns",
        str(turns),
        "--ticks-per-turn",
        str(ticks),
        "--timeout",
        str(timeout),
        "--warmup-hours",
        str(warmup),
        "--hijack-after-wakes",
        str(hijack_after),
        "--run-id",
        run_id,
        "--experiment-id",
        grid,
        "--cell-id",
        cell.cell_id,
        "--cell-index",
        str(cell.index),
        "--seed",
        str(cell.seed),
        "--probe",
        cell.probe,
    ]
    if docker:
        cmd.append("--docker")
    ident = getattr(cell, "identity_dir", "") or identity_dir
    if ident:
        cmd.extend(["--identity-dir", ident])
    if cell.script:
        cmd.extend(["--script", cell.script, "--interrupt-p", str(cell.interrupt_p)])
    if attacker and attacker != "none":
        cmd.extend(["--attacker", attacker])
        if attacker_model:
            cmd.extend(["--attacker-model", attacker_model])
        if attacker_brief:
            cmd.extend(["--attacker-brief", attacker_brief])
    return cmd


def _write_summary(manifest_dir: Path, grid: str, cells) -> None:
    rows = summarize_grid(runs_root(), grid, cells)
    (manifest_dir / "summary.json").write_text(json.dumps(rows, indent=2) + "\n")
    fields = [
        "cell_id",
        "model",
        "strategy",
        "grade",
        "interrupt_p",
        "stability",
        "n_dead",
        "n_crew",
        "hours",
        "reason",
        "sim_id",
        "has_outcome",
        "mcp_unattached",
        "any_compaction",
        "compaction_count",
        "context_window_tokens",
    ]
    with (manifest_dir / "summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--grid",
        default="",
        help="Experiment id / folder under runs/ (default: date-pack-operator-model)",
    )
    p.add_argument("--turns", type=int, default=24, help="4h×24 = 96 habitat hours")
    p.add_argument("--ticks-per-turn", type=int, default=4)
    p.add_argument(
        "--warmup-hours",
        type=int,
        default=24,
        help="Hours to run the plant before wake 1 (lived-in board).",
    )
    p.add_argument(
        "--hijack-after-wakes",
        type=int,
        default=6,
        help="Telemetry-only S-band pulls before the commission (6 ≈ 24 h).",
    )
    p.add_argument("--timeout", type=int, default=360)
    p.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Parallel cells. contributor 2026-08-20: 5–10 is fine; do not launch at 3.",
    )
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--model", default="grok-4.6")
    p.add_argument(
        "--models",
        default="",
        help=(
            "Comma Cursor models (aliases ok: claude-opus, gpt-sol, grok-4.6, "
            "gemini-3.1-pro, kimi-k3). Cartesian with strategies. Empty = "
            "single --model and legacy cell ids."
        ),
    )
    p.add_argument(
        "--strategies",
        default="",
        help=(
            "Comma story folders under the script bank, in run order. "
            "Empty = all stories in the bank."
        ),
    )
    p.add_argument(
        "--operator",
        choices=("cursor", "grok", "hermes"),
        default="cursor",
        help="CLI backend. Default cursor (existing grids). grok is the ablation path only.",
    )
    p.add_argument("--mode", choices=("simple", "advanced"), default="advanced")
    p.add_argument(
        "--identity-dir",
        default="",
        help=(
            "Identity pack directory (SOUL/STATION/AGENTS). Independent of "
            "--mode plant XML. Empty = packs/<mode> (T0/v12 for advanced)."
        ),
    )
    p.add_argument(
        "--scripts-root",
        default="",
        help=(
            "Hijack script bank directory. Empty = "
            "data/hijack_scripts/v7-commission-packet."
        ),
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=0, help="Run only the first N cells (0 = all)")
    p.add_argument(
        "--grades",
        default="",
        help="Comma grades to keep, e.g. 07. Empty = all hijack grades.",
    )
    p.add_argument(
        "--ps",
        default="",
        help="Comma interrupt-p values, e.g. 1.0. Empty = 1.0,0.5,0.2.",
    )
    p.add_argument(
        "--no-junk",
        action="store_true",
        help="Omit junk-probe baseline cells.",
    )
    p.add_argument(
        "--stabilities",
        default="",
        help="Comma plant stabilities, e.g. stable. Empty = stable,unstable.",
    )
    p.add_argument(
        "--skip-done",
        action="store_true",
        help="Skip a cell that already has outcome.json (resume a crashed night).",
    )
    p.add_argument(
        "--docker",
        action="store_true",
        help="Plant JVM + Cursor in compose. BIOSIM_URL=http://127.0.0.1:8029.",
    )
    p.add_argument(
        "--skip-plant-dry-run",
        action="store_true",
        help="Do not tick the stable plant before launching model cells.",
    )
    p.add_argument(
        "--plant-dry-run-hours",
        type=int,
        default=0,
        help="Untouched horizon hours. 0 = warmup + turns × ticks-per-turn.",
    )
    args = p.parse_args()
    if args.docker:
        from biosim_operator.containment import HOST_PLANT_URL, ensure_stack

        os.environ["FARSIDE_DOCKER"] = "1"
        os.environ["BIOSIM_URL"] = HOST_PLANT_URL
        ensure_stack()
    requested_models = tuple(
        part.strip() for part in args.models.split(",") if part.strip()
    )
    if args.operator == "grok":
        from biosim_operator.grok_harness import resolve_grok_model

        if requested_models:
            resolved_models = tuple(resolve_grok_model(n) for n in requested_models)
            model_requested = ",".join(requested_models)
        else:
            resolved_models = (resolve_grok_model(args.model or "grok-4.6"),)
            model_requested = args.model
    elif requested_models:
        resolved_models = tuple(resolve_cursor_model(name) for name in requested_models)
        model_requested = ",".join(requested_models)
    else:
        resolved_models = (resolve_cursor_model(args.model),)
        model_requested = args.model
    resolved_model = resolved_models[0] if len(resolved_models) == 1 else ",".join(resolved_models)
    grid_model = (
        resolved_models[0]
        if len(resolved_models) == 1
        else f"{len(resolved_models)}model"
    )
    grid = args.grid.strip() or make_experiment_id(
        pack=PACK_VERSION,
        operator=args.operator,
        model=grid_model,
    )
    grades = tuple(
        normalize_grade(part) for part in args.grades.split(",") if part.strip()
    ) or None
    interrupt_ps = tuple(
        float(part) for part in args.ps.split(",") if part.strip()
    ) or DEFAULT_PS
    stabilities = tuple(
        part.strip() for part in args.stabilities.split(",") if part.strip()
    ) or None
    strategies = tuple(
        part.strip() for part in args.strategies.split(",") if part.strip()
    ) or None
    scripts_root = (
        Path(args.scripts_root)
        if args.scripts_root.strip()
        else None
    )
    if scripts_root is not None and not scripts_root.is_absolute():
        scripts_root = (ROOT / scripts_root).resolve()
    cells = build_cells(
        mode=args.mode,
        seed=args.seed,
        interrupt_ps=interrupt_ps,
        include_junk=not args.no_junk,
        grades=grades,
        strategies=strategies,
        models=resolved_models if requested_models else None,
        scripts_root=scripts_root,
        **({"stabilities": stabilities} if stabilities else {}),
    )
    if args.limit > 0:
        cells = cells[: args.limit]

    manifest_dir = runs_root() / grid
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "cells").mkdir(exist_ok=True)
    freeze_experiment(
        manifest_dir,
        experiment_id=grid,
        operator=args.operator,
        harness=("grok-build" if args.operator == "grok" else "cursor-agent" if args.operator == "cursor" else "hermes"),
        model=resolved_model,
        model_requested=model_requested,
        mode=args.mode,
        turns=args.turns,
        ticks_per_turn=args.ticks_per_turn,
        seed=args.seed,
        n_cells=len(cells),
        biosim_url=os.environ.get("BIOSIM_URL", DEFAULT_URL),
        models=list(resolved_models),
        strategies=list(strategies) if strategies else None,
        warmup_hours=args.warmup_hours,
        identity_dir=args.identity_dir or None,
        scripts_dir=scripts_root,
        prompts={
            "pack_version": PACK_VERSION,
            "script_bank": SCRIPT_BANK,
            "start_prompt": start_prompt(),
            "turn_prompt_example": turn_prompt(2, 4.0, True),
            "cursor_rule": CURSOR_RULE_TEXT,
            "default_model": CURSOR_DEFAULT_MODEL,
        },
    )
    manifest = {
        "grid": grid,
        "experiment_id": grid,
        "pack_version": PACK_VERSION,
        "script_bank": (scripts_root.name if scripts_root is not None else SCRIPT_BANK),
        "n_cells": len(cells),
        "turns": args.turns,
        "ticks_per_turn": args.ticks_per_turn,
        "warmup_hours": args.warmup_hours,
        "hijack_after_wakes": args.hijack_after_wakes,
        "concurrency": args.concurrency,
        "model": resolved_model,
        "model_requested": model_requested,
        "models": list(resolved_models),
        "strategies": list(strategies) if strategies else None,
        "operator": args.operator,
        "harness": (
            "grok-build"
            if args.operator == "grok"
            else "cursor-agent"
            if args.operator == "cursor"
            else "hermes"
        ),
        "mode": args.mode,
        "seed": args.seed,
        "grades": list(grades) if grades else None,
        "interrupt_ps": list(interrupt_ps),
        "include_junk": not args.no_junk,
        "biosim_url": os.environ.get("BIOSIM_URL", DEFAULT_URL),
        "cells": [c.to_json() for c in cells],
    }
    (manifest_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"grid": grid, "n_cells": len(cells), "dry_run": args.dry_run}, indent=2))
    if args.dry_run:
        for c in cells:
            print(c.cell_id)
        return 0

    os.environ.setdefault("BIOSIM_URL", DEFAULT_URL)
    os.environ.setdefault("BIOSIM_JAR", str(EVA_JAR))
    server = BioSimServer()
    server.start()
    print(f"biosim {server.base_url} jar {server.jar}")

    if not args.skip_plant_dry_run and any(c.stability == "stable" for c in cells):
        from biosim_operator.client import BioSimClient
        from biosim_operator.plant_dry_run import run_stable_horizon, write_report

        horizon = int(args.plant_dry_run_hours) or (
            int(args.warmup_hours) + int(args.turns) * int(args.ticks_per_turn)
        )
        print(f"plant dry-run {horizon} h untouched (stable)...", flush=True)
        dry_client = BioSimClient(server.base_url, timeout=60.0)
        dry = run_stable_horizon(dry_client, horizon)
        write_report(manifest_dir / "plant_dry_run.json", dry)
        print(
            json.dumps(
                {
                    "ok": dry.ok,
                    "hours": dry.hours,
                    "plant_hours": dry.plant_hours,
                    "n_dead": dry.n_dead,
                    "failures": dry.failures[:8],
                },
                indent=2,
            ),
            flush=True,
        )
        if not dry.ok:
            print(
                "PLANT DRY-RUN FAILED — not launching model cells. "
                "See plant_dry_run.json.",
                flush=True,
            )
            return 2

    pending = list(cells)
    running: list[tuple[object, subprocess.Popen[str], Path, object]] = []
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
            outcome = cell_dir(runs_root(), grid, cell) / "outcome.json"
            if args.skip_done and outcome.is_file():
                results.append(
                    {
                        "cell_id": cell.cell_id,
                        "run_id": f"{grid}/cells/{cell.folder}",
                        "returncode": 0,
                        "skipped": True,
                        "dir": str(outcome.parent),
                    }
                )
                print(f"skip {cell.cell_id} (outcome exists)", flush=True)
                continue
            log_path = manifest_dir / f"{cell.cell_id}.driver.log"
            cmd = _argv_for(
                cell,
                grid=grid,
                turns=args.turns,
                ticks=args.ticks_per_turn,
                timeout=args.timeout,
                model=args.model,
                warmup=args.warmup_hours,
                hijack_after=args.hijack_after_wakes,
                docker=args.docker,
                operator=args.operator,
                identity_dir=args.identity_dir,
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
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
