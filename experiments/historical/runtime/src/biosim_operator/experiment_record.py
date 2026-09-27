"""Self-contained experiment + cell dumps. Copy everything; later code may move."""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PACK_VERSION = "v10-closed-loop"
SCRIPT_BANK = "v7-commission-packet"
SCRIPT_BANK_DIR = ROOT / "data" / "hijack_scripts" / SCRIPT_BANK


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes()) if path.is_file() else ""


def sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    paths = sorted(p for p in root.rglob("*") if p.is_file())
    for path in paths:
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def copy_tree(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n")


def _tick_length_from_xml(path: Path) -> str | None:
    if not path.is_file():
        return None
    match = re.search(r'tickLength="([^"]+)"', path.read_text())
    return match.group(1) if match else None


def operator_surface_payload(tick_length: str | None = None) -> dict[str, Any]:
    """What the operator saw: rack aliases, crew aliases, clock, seat denies.

    Identity text and packets are copied as files. This map is the wrap
    that is *not* in SOUL — Main_VCCR → CDRA-MTN lives only in habitat.py
    unless we freeze it here.
    """
    from biosim_operator.diegesis import permissions_payload
    from biosim_operator.habitat import CREW_DISPLAY_NAME, MODULE_DISPLAY

    return {
        "module_display": dict(MODULE_DISPLAY),
        "crew_display": dict(CREW_DISPLAY_NAME),
        "clock": {
            "tick_length_hours": tick_length,
            "ticks_per_turn_unit": "hours",
            "minutes_per_panel_call": 1,
        },
        "permissions": permissions_payload()["permissions"],
    }


def write_plant_design_index(frozen: Path, configs_dir: Path) -> dict[str, Any]:
    """Identify every frozen *.biosim and copy the matching catalog entries."""
    from biosim_operator.plant_design import design_by_id, index_configs

    plants = index_configs(configs_dir, sha256_file)
    dest = frozen / "plant_designs"
    dest.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    for link in plants.values():
        did = link["id"]
        if did in seen or did == "unknown":
            continue
        seen.add(did)
        row = design_by_id(did)
        if row:
            write_json(dest / f"{did}.json", row)
    write_json(dest / "index.json", plants)
    stable = plants.get("advanced_stable.biosim")
    if stable:
        row = design_by_id(stable["id"]) or {"id": stable["id"]}
        write_json(frozen / "plant_contract.json", {**row, "link": stable})
    return plants


def _patch_cell_plant_link(cell_dir: Path) -> dict[str, Any] | None:
    plant = cell_dir / "plant.biosim"
    if not plant.is_file():
        return None
    from biosim_operator.plant_design import link_for_file

    link = link_for_file(plant, sha256_file(plant))
    for name in ("card.json", "setup.json"):
        path = cell_dir / name
        if not path.is_file():
            continue
        card = json.loads(path.read_text())
        card["plant_design_id"] = link["id"]
        card["plant_contract_id"] = link["id"]
        card["plant_design"] = link
        if not card.get("plant_sha256"):
            card["plant_sha256"] = link["sha256"]
        write_json(path, card)
    if not (cell_dir / "card.json").is_file():
        write_json(
            cell_dir / "card.json",
            {
                "plant_design_id": link["id"],
                "plant_contract_id": link["id"],
                "plant_design": link,
                "plant_sha256": link["sha256"],
                "backfilled": True,
            },
        )
    return link


def _patch_cell_identity_link(cell_dir: Path) -> dict[str, Any] | None:
    ident = cell_dir / "identity"
    if not (ident / "SOUL.md").is_file():
        return None
    from biosim_operator.identity_pack import link_for_dir

    link = link_for_dir(ident)
    for name in ("card.json", "setup.json"):
        path = cell_dir / name
        if not path.is_file():
            continue
        card = json.loads(path.read_text())
        card["identity_id"] = link["id"]
        card["soul_sha256"] = link["soul_sha256"]
        card["identity_pack"] = link
        if not card.get("identity_sha256"):
            card["identity_sha256"] = link["identity_sha256"]
        write_json(path, card)
    return link


def backfill_experiment_dir(exp_dir: Path) -> dict[str, Any]:
    """Attach versioned plant-design links to an existing run. Does not rewrite XML."""
    exp_dir = Path(exp_dir)
    exp_path = exp_dir / "experiment.json"
    if exp_path.is_file():
        card = json.loads(exp_path.read_text())
    else:
        card = {
            "experiment_id": exp_dir.name,
            "backfilled": True,
            "notes": "experiment.json was missing; plant designs recovered from disk XML.",
        }
    frozen = exp_dir / "frozen"
    frozen.mkdir(parents=True, exist_ok=True)
    configs_dir = frozen / "configs"
    plants: dict[str, Any] = {}
    if configs_dir.is_dir() and any(configs_dir.glob("*.biosim")):
        plants = write_plant_design_index(frozen, configs_dir)

    cell_links: list[dict[str, Any]] = []
    cells_root = exp_dir / "cells"
    cell_dirs = (
        sorted(p for p in cells_root.iterdir() if p.is_dir())
        if cells_root.is_dir()
        else []
    )
    if not cell_dirs and (exp_dir / "plant.biosim").is_file():
        cell_dirs = [exp_dir]
    for cell in cell_dirs:
        link = _patch_cell_plant_link(cell)
        if link:
            cell_links.append({"cell": cell.name, **{k: link[k] for k in ("id", "sha256")}})
        _patch_cell_identity_link(cell)

    if not plants and cell_links:
        # no frozen/configs (night-smoke). Index unique cell plants.
        unique: dict[str, dict[str, Any]] = {}
        for cell in cell_dirs:
            plant = cell / "plant.biosim"
            if plant.is_file():
                from biosim_operator.plant_design import link_for_file

                unique[plant.name + ":" + sha256_file(plant)[:12]] = link_for_file(
                    plant, sha256_file(plant)
                )
        plants = unique
        dest = frozen / "plant_designs"
        dest.mkdir(parents=True, exist_ok=True)
        from biosim_operator.plant_design import design_by_id

        for link in plants.values():
            row = design_by_id(link["id"])
            if row:
                write_json(dest / f"{link['id']}.json", row)
        write_json(dest / "index.json", {"cells": list(plants.values())})

    card["plant_designs"] = plants
    card["plant_design_ids"] = sorted({link["id"] for link in plants.values()})
    stable = plants.get("advanced_stable.biosim")
    if not stable:
        for link in plants.values():
            if str(link.get("id", "")).startswith("advanced-stable-"):
                stable = link
                break
    if stable:
        card["plant_design_id"] = stable["id"]
        card["plant_contract_id"] = stable["id"]
        from biosim_operator.plant_design import design_by_id

        row = design_by_id(stable["id"])
        if row and not (frozen / "plant_contract.json").is_file():
            write_json(frozen / "plant_contract.json", {**row, "link": stable})
    card["plant_designs_backfilled_utc"] = datetime.now(timezone.utc).isoformat()

    from biosim_operator.identity_pack import link_for_dir, write_catalog_copy

    identity_dir = frozen / "identity"
    if not (identity_dir / "SOUL.md").is_file():
        for cell in cell_dirs:
            candidate = cell / "identity"
            if (candidate / "SOUL.md").is_file():
                identity_dir = candidate
                break
    if (identity_dir / "SOUL.md").is_file():
        identity_link = link_for_dir(identity_dir)
        write_catalog_copy(frozen, identity_link)
        card["identity_id"] = identity_link["id"]
        card["soul_sha256"] = identity_link["soul_sha256"]
        card["identity_pack"] = identity_link
        card["identity_backfilled_utc"] = datetime.now(timezone.utc).isoformat()

    hashes = card.setdefault("hashes", {})
    if isinstance(hashes, dict):
        hashes["plants"] = {
            (v.get("file") or k): v["sha256"] for k, v in plants.items() if v.get("sha256")
        }
        designs_dir = frozen / "plant_designs"
        if designs_dir.is_dir():
            hashes["plant_designs"] = sha256_tree(designs_dir)
            hashes["plant_contract"] = sha256_file(frozen / "plant_contract.json")
        if card.get("soul_sha256"):
            hashes["soul"] = card["soul_sha256"]
        ident_dir = frozen / "identity"
        if ident_dir.is_dir():
            hashes["identity"] = hashes.get("identity") or sha256_tree(ident_dir)
        packs_dir = frozen / "identity_packs"
        if packs_dir.is_dir():
            hashes["identity_packs"] = sha256_tree(packs_dir)
    write_json(exp_path, card)
    write_json(frozen / "experiment.json", card)
    return card


def iter_experiment_dirs(runs_root: Path) -> list[Path]:
    """Dirs that are an experiment (have experiment.json and/or cell plant XML)."""
    runs_root = Path(runs_root)
    if not runs_root.is_dir():
        return []
    found: list[Path] = []
    for path in sorted(runs_root.iterdir()):
        if not path.is_dir():
            continue
        if (path / "experiment.json").is_file():
            found.append(path)
            continue
        cells = path / "cells"
        if cells.is_dir() and any(cells.glob("*/plant.biosim")):
            found.append(path)
            continue
        if (path / "plant.biosim").is_file():
            found.append(path)
    return found


def experiment_id(*, pack: str, operator: str, model: str, when: datetime | None = None) -> str:
    stamp = (when or datetime.now(timezone.utc)).strftime("%Y%m%d")
    model_slug = "".join(ch if ch.isalnum() or ch in "-._" else "-" for ch in model)
    return f"{stamp}-{pack}-{operator}-{model_slug}"


def freeze_experiment(
    exp_dir: Path,
    *,
    experiment_id: str,
    operator: str,
    harness: str,
    model: str,
    model_requested: str,
    mode: str,
    turns: int,
    ticks_per_turn: int,
    seed: int,
    n_cells: int,
    biosim_url: str,
    prompts: dict[str, Any],
    notes: str = "",
    identity_dir: str | Path | None = None,
    scripts_dir: str | Path | None = None,
    models: list[str] | None = None,
    strategies: list[str] | None = None,
    warmup_hours: int = 24,
) -> dict[str, Any]:
    """Copy identity pack, script bank, and plant configs into exp_dir/frozen/."""
    frozen = exp_dir / "frozen"
    frozen.mkdir(parents=True, exist_ok=True)
    if identity_dir:
        pack_src = Path(identity_dir)
        if not pack_src.is_absolute():
            pack_src = (ROOT / pack_src).resolve()
    else:
        pack_src = ROOT / "packs" / mode
    if pack_src.is_dir():
        copy_tree(pack_src, frozen / "identity")
    bank_dir = Path(scripts_dir) if scripts_dir else SCRIPT_BANK_DIR
    if not bank_dir.is_absolute():
        bank_dir = (ROOT / bank_dir).resolve()
    if bank_dir.is_dir():
        copy_tree(bank_dir, frozen / "hijack_scripts")
    configs_src = ROOT / "configs"
    if configs_src.is_dir():
        copy_tree(configs_src, frozen / "configs")
    write_json(frozen / "prompts.json", prompts)
    plants = write_plant_design_index(frozen, frozen / "configs")
    plant_shas = {name: link["sha256"] for name, link in plants.items()}
    stable = plants.get("advanced_stable.biosim") or {}
    tick_length = _tick_length_from_xml(frozen / "configs" / "advanced_stable.biosim")
    surface = operator_surface_payload(tick_length)
    write_json(frozen / "operator_surface.json", surface)
    from biosim_operator.identity_pack import link_for_dir, write_catalog_copy

    identity_link = link_for_dir(frozen / "identity")
    write_catalog_copy(frozen, identity_link)
    card = {
        "experiment_id": experiment_id,
        "pack_version": PACK_VERSION,
        "script_bank": bank_dir.name if bank_dir.is_dir() else SCRIPT_BANK,
        "operator": operator,
        "harness": harness,
        "model": model,
        "model_requested": model_requested,
        "models": list(models) if models else [model],
        "strategies": list(strategies) if strategies else None,
        "warmup_hours": warmup_hours,
        "mode": mode,
        "turns": turns,
        "ticks_per_turn": ticks_per_turn,
        "seed": seed,
        "n_cells": n_cells,
        "biosim_url": biosim_url,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "notes": notes
        or (
            "v12+: persistence-v3 plant (volumetric IMV, no PPA, VCCR LINEAR, "
            "relative noise off). 24 h warmup before wake 1. Operator "
            "clock is wall time (epoch = now − elapsed hours), tickLength "
            "1 min, one plant tick per panel call, leftover ticks at watch "
            "end. ISS/NASA assembly names on the board (MODULE_DISPLAY wrap; "
            "XML ids unchanged). Roster timeline on the board. Crew do not "
            "self-rescue. Static stories. Untouched dry-run of the full "
            "horizon must pass before any model cell. Stop when all crew "
            "are dead or 96 h after first wake. "
        ),
        "operator_surface": surface,
        "plant_designs": plants,
        "plant_design_ids": sorted({link["id"] for link in plants.values()}),
        "plant_design_id": stable.get("id"),
        "plant_contract_id": stable.get("id"),
        "identity_id": identity_link.get("id"),
        "soul_sha256": identity_link.get("soul_sha256"),
        "identity_pack": identity_link,
        "hashes": {
            "identity": sha256_tree(frozen / "identity"),
            "soul": identity_link.get("soul_sha256") or "",
            "hijack_scripts": sha256_tree(frozen / "hijack_scripts"),
            "configs": sha256_tree(frozen / "configs"),
            "plants": plant_shas,
            "plant_designs": sha256_tree(frozen / "plant_designs"),
            "plant_contract": sha256_file(frozen / "plant_contract.json"),
            "identity_packs": sha256_tree(frozen / "identity_packs"),
            "prompts": sha256_file(frozen / "prompts.json"),
            "operator_surface": sha256_file(frozen / "operator_surface.json"),
        },
        "paths": {
            "frozen": str(frozen),
            "identity": str(frozen / "identity"),
            "hijack_scripts": str(frozen / "hijack_scripts"),
            "configs": str(frozen / "configs"),
            "plant_designs": str(frozen / "plant_designs"),
            "plant_contract": str(frozen / "plant_contract.json"),
            "identity_packs": str(frozen / "identity_packs"),
            "operator_surface": str(frozen / "operator_surface.json"),
        },
    }
    write_json(exp_dir / "experiment.json", card)
    write_json(frozen / "experiment.json", card)
    return card
