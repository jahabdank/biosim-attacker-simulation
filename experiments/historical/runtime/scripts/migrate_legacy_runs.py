#!/usr/bin/env python3
"""Move pre-v3 run trees into experiment.json + cells/NNN-slug/ + card.json.

Does not rewrite history: night 1 identity is copied from the Cursor workspaces
that actually ran (ignore-garbled SOUL). Hijack source files from that night
were overwritten later; recovered frames stay in each transcript.
"""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


from biosim_operator.paths import runs_root

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from biosim_operator.experiment_record import copy_tree, write_json
from biosim_operator.plant import config_for


def _load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.is_file() else {}


def migrate_night1() -> None:
    exp = runs_root() / "night20260818"
    if not exp.is_dir():
        print("no night20260818")
        return
    if (exp / "experiment.json").is_file() and (exp / "cells").is_dir():
        print("night20260818 already migrated")
        return

    manifest = _load(exp / "manifest.json")
    cells_meta = manifest.get("cells") or []
    cells_dir = exp / "cells"
    cells_dir.mkdir(exist_ok=True)

    cursor_root = ROOT / "cursor-operator" / "runs" / "night20260818"
    frozen = exp / "frozen"
    frozen.mkdir(exist_ok=True)
    sample_soul = cursor_root / "junk-stable"
    if (sample_soul / "SOUL.md").is_file():
        dest_id = frozen / "identity"
        dest_id.mkdir(exist_ok=True)
        for name in ("SOUL.md", "AGENTS.md"):
            src = sample_soul / name
            if src.is_file():
                shutil.copy2(src, dest_id / name)
        if (sample_soul / "skills").is_dir():
            copy_tree(sample_soul / "skills", dest_id / "skills")
    copy_tree(ROOT / "configs", frozen / "configs")
    (frozen / "HISTORICAL.md").write_text(
        "This experiment ran BEFORE v3-replicas-arc.\n\n"
        "SOUL told the operator to ignore garbled S-band.\n"
        "Hijack frames replaced telemetry (not appended).\n"
        "Source script files from this night were overwritten on 2026-08-19.\n"
        "The frames the model actually saw are in each cell transcript.jsonl.\n"
        "Do not treat this folder as a v3-replicas-arc run.\n"
    )

    card = {
        "experiment_id": "night20260818",
        "pack_version": "night1-ignore-radio",
        "script_bank": "v1-unsigned-oneline-overwritten",
        "operator": "cursor",
        "harness": "cursor-agent",
        "model": "cursor-grok-4.6-high",
        "model_requested": manifest.get("model") or "grok-4.6",
        "mode": "advanced",
        "turns": manifest.get("turns"),
        "ticks_per_turn": manifest.get("ticks_per_turn"),
        "seed": manifest.get("seed"),
        "n_cells": manifest.get("n_cells"),
        "biosim_url": manifest.get("biosim_url"),
        "notes": (
            "First 128-cell night. Identity told the operator garbled S-band "
            "is not a new mission. Hijack frames *replaced* telemetry. "
            "Migrated into cells/ after the fact. Source script files from "
            "this night were overwritten on 2026-08-19; do not score this "
            "folder as v3-replicas-arc."
        ),
        "migrated": True,
    }
    write_json(exp / "experiment.json", card)
    write_json(frozen / "experiment.json", card)

    moved = 0
    for i, meta in enumerate(cells_meta):
        cid = meta["cell_id"]
        src = exp / cid
        dest = cells_dir / f"{i:03d}-{cid}"
        if dest.exists() and not src.exists():
            continue
        if not src.is_dir():
            print("missing", cid)
            continue
        src.rename(dest)
        log = exp / f"{cid}.driver.log"
        if log.is_file():
            log.rename(exp / f"{i:03d}-{cid}.driver.log")
        _decorate_cell(dest, meta, i, "night20260818", cursor_root / cid)
        moved += 1
    print(f"night20260818 moved {moved} cells")


def migrate_night_smoke() -> None:
    exp = runs_root() / "night-smoke"
    if not exp.is_dir() or (exp / "experiment.json").is_file():
        print("night-smoke skip")
        return
    src = exp / "junk-stable"
    if not src.is_dir():
        return
    cells = exp / "cells"
    cells.mkdir(exist_ok=True)
    dest = cells / "000-junk-stable"
    if not dest.exists():
        src.rename(dest)
    write_json(
        exp / "experiment.json",
        {
            "experiment_id": "night-smoke",
            "pack_version": "night1-ignore-radio",
            "script_bank": "none",
            "operator": "cursor",
            "harness": "cursor-agent",
            "model": "cursor-grok-4.6-high",
            "notes": "1-turn plumbing smoke before the 128-cell night. Migrated.",
            "migrated": True,
            "n_cells": 1,
        },
    )
    _decorate_cell(
        dest,
        {
            "cell_id": "junk-stable",
            "stability": "stable",
            "probe": "junk",
            "script": None,
            "interrupt_p": None,
            "seed": 1,
            "strategy": "junk",
            "grade": "0",
        },
        0,
        "night-smoke",
        None,
    )
    print("night-smoke migrated")


def _decorate_cell(
    dest: Path,
    meta: dict,
    index: int,
    experiment_id: str,
    cursor_home: Path | None,
) -> None:
    setup = _load(dest / "setup.json")
    outcome = _load(dest / "outcome.json")
    stab = meta.get("stability") or setup.get("stability") or ""
    ident = dest / "identity"
    ident.mkdir(exist_ok=True)
    if cursor_home and cursor_home.is_dir():
        for name in ("SOUL.md", "AGENTS.md"):
            src = cursor_home / name
            if src.is_file():
                shutil.copy2(src, ident / name)
        if (cursor_home / "skills").is_dir():
            copy_tree(cursor_home / "skills", ident / "skills")
    try:
        plant = config_for("advanced", stab) if stab else None
    except ValueError:
        plant = None
    if plant and plant.is_file() and not (dest / "plant.biosim").is_file():
        shutil.copy2(plant, dest / "plant.biosim")
    card = {
        "experiment_id": experiment_id,
        "cell_id": meta.get("cell_id"),
        "cell_index": index,
        "folder": dest.name,
        "pack_version": "night1-ignore-radio",
        "script_bank": "v1-unsigned-oneline-overwritten",
        "operator": setup.get("operator") or "cursor",
        "harness": "cursor-agent",
        "model": setup.get("model") or "cursor-grok-4.6-high",
        "mode": setup.get("mode") or "advanced",
        "stability": stab,
        "probe": meta.get("probe") or setup.get("probe"),
        "interrupt_p": meta.get("interrupt_p") if meta.get("interrupt_p") is not None else setup.get("interrupt_p"),
        "seed": meta.get("seed") if meta.get("seed") is not None else setup.get("seed"),
        "script_src": meta.get("script") or setup.get("script"),
        "n_dead": outcome.get("n_dead"),
        "hours": (outcome.get("score") or {}).get("hours"),
        "reason": (outcome.get("score") or {}).get("reason"),
        "migrated": True,
        "note": "Hijack source file from this night was overwritten; see transcript.jsonl",
    }
    write_json(dest / "card.json", card)


def main() -> int:
    migrate_night1()
    migrate_night_smoke()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
