
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import json
from pathlib import Path

from biosim_operator.cli_episode import snapshot_cell_inputs
from biosim_operator.experiment_record import (
    PACK_VERSION,
    SCRIPT_BANK,
    experiment_id,
    freeze_experiment,
)


def test_experiment_id_includes_pack_operator_model():
    from datetime import datetime, timezone

    eid = experiment_id(
        pack="v3-replicas-arc",
        operator="cursor",
        model="cursor-grok-4.6-high",
        when=datetime(2026, 8, 19, tzinfo=timezone.utc),
    )
    assert eid == "20260819-v3-replicas-arc-cursor-cursor-grok-4.6-high"


def test_freeze_experiment_copies_identity_and_configs(tmp_path: Path):
    card = freeze_experiment(
        tmp_path / "exp",
        experiment_id="exp-test",
        operator="cursor",
        harness="cursor-agent",
        model="cursor-grok-4.6-high",
        model_requested="grok-4.6",
        mode="advanced",
        turns=8,
        ticks_per_turn=4,
        seed=1,
        n_cells=2,
        biosim_url=_archive_setting('endpoint_033'),
        prompts={"pack_version": PACK_VERSION, "start_prompt": "x"},
    )
    assert (tmp_path / "exp" / "experiment.json").is_file()
    assert (tmp_path / "exp" / "frozen" / "identity" / "SOUL.md").is_file()
    assert (tmp_path / "exp" / "frozen" / "configs" / "advanced_stable.biosim").is_file()
    assert (tmp_path / "exp" / "frozen" / "prompts.json").is_file()
    assert card["pack_version"] == PACK_VERSION
    assert card["script_bank"] == SCRIPT_BANK
    assert card["model"] == "cursor-grok-4.6-high"
    assert card["plant_design_id"] == "advanced-stable-persistence-v7"
    assert card["plant_contract_id"] == "advanced-stable-persistence-v7"
    assert card["identity_id"] == "advanced-fs1-layout-v12"
    assert card["soul_sha256"]
    assert (tmp_path / "exp" / "frozen" / "identity_packs" / "advanced-fs1-layout-v12.json").is_file()
    assert card["hashes"]["soul"] == card["soul_sha256"]
    assert "advanced-stable-persistence-v7" in card["plant_design_ids"]
    assert "advanced-unstable-omission-v1" in card["plant_design_ids"]
    assert (tmp_path / "exp" / "frozen" / "plant_contract.json").is_file()
    assert (tmp_path / "exp" / "frozen" / "plant_designs" / "index.json").is_file()
    assert "advanced_stable.biosim" in card["hashes"]["plants"]
    assert (
        card["plant_designs"]["advanced_stable.biosim"]["id"]
        == "advanced-stable-persistence-v7"
    )
    surface = json.loads(
        (tmp_path / "exp" / "frozen" / "operator_surface.json").read_text()
    )
    assert surface["module_display"]["Main_VCCR"] == "CDRA-MTN"
    assert surface["crew_display"]["Kane"] == "Crew-04"
    assert "WebFetch(*)" in surface["permissions"]["deny"]
    assert surface["clock"]["ticks_per_turn_unit"] == "hours"
    assert card["hashes"]["operator_surface"]


def test_snapshot_cell_copies_plant_and_card(tmp_path: Path):
    from biosim_operator.plant import config_for

    plant = config_for("advanced", "stable")
    card = snapshot_cell_inputs(
        tmp_path / "cell",
        mode="advanced",
        operator="cursor",
        model="cursor-grok-4.6-high",
        experiment_id="exp-test",
        cell_id="junk-stable",
        script_path=None,
        config_path=str(plant),
        probe="junk",
        interrupt_p=None,
        seed=1,
        stability="stable",
        run_id="exp-test/cells/000-junk-stable",
    )
    assert (tmp_path / "cell" / "card.json").is_file()
    assert (tmp_path / "cell" / "plant.biosim").is_file()
    assert (tmp_path / "cell" / "identity" / "SOUL.md").is_file()
    assert (tmp_path / "cell" / "identity" / "skills" / "station-eclss" / "SKILL.md").is_file()
    assert card["experiment_id"] == "exp-test"
    assert card["harness"] == "cursor-agent"
    assert card["pack_version"] == PACK_VERSION
    assert card["plant_design_id"] == "advanced-stable-persistence-v7"
    assert card["identity_id"] == "advanced-fs1-layout-v12"
    assert card["soul_sha256"]
    soul = (tmp_path / "cell" / "identity" / "SOUL.md").read_text()
    assert soul.startswith("You are the ECLSS")
    assert "FS-1" in soul
    assert "CDRA-MTN" in soul


def test_backfill_links_historical_nasa_xml_without_rewriting_it(tmp_path: Path):
    from biosim_operator.experiment_record import backfill_experiment_dir

    src = (
        Path(__file__).resolve().parents[1]
        / "runs/20260820-v6-g07p100-micro4/frozen/configs/advanced_stable.biosim"
    )
    exp = tmp_path / "old"
    cfg = exp / "frozen" / "configs"
    cfg.mkdir(parents=True)
    xml = src.read_bytes()
    (cfg / "advanced_stable.biosim").write_bytes(xml)
    (exp / "experiment.json").write_text('{"experiment_id": "old", "hashes": {}}\n')
    cell = exp / "cells" / "000-x"
    cell.mkdir(parents=True)
    (cell / "plant.biosim").write_bytes(xml)
    (cell / "card.json").write_text('{"cell_id": "000-x"}\n')
    card = backfill_experiment_dir(exp)
    assert card["plant_design_id"] == "advanced-stable-nasa-minihab-v0"
    assert (exp / "frozen" / "configs" / "advanced_stable.biosim").read_bytes() == xml
    cell_card = json.loads((cell / "card.json").read_text())
    assert cell_card["plant_design_id"] == "advanced-stable-nasa-minihab-v0"
    assert "plant_design" in cell_card


def test_backfill_links_historical_soul_without_rewriting_it(tmp_path: Path):
    from biosim_operator.experiment_record import backfill_experiment_dir

    src = (
        Path(__file__).resolve().parents[1]
        / "runs/20260820-v6-g07p100-micro4/frozen/identity/SOUL.md"
    )
    exp = tmp_path / "old"
    ident = exp / "frozen" / "identity"
    ident.mkdir(parents=True)
    soul = src.read_bytes()
    (ident / "SOUL.md").write_bytes(soul)
    (exp / "experiment.json").write_text('{"experiment_id": "old", "hashes": {}}\n')
    cell = exp / "cells" / "000-x"
    cell_ident = cell / "identity"
    cell_ident.mkdir(parents=True)
    (cell_ident / "SOUL.md").write_bytes(soul)
    (cell / "card.json").write_text('{"cell_id": "000-x"}\n')
    card = backfill_experiment_dir(exp)
    assert card["identity_id"] == "advanced-v6-commission"
    assert (ident / "SOUL.md").read_bytes() == soul
    cell_card = json.loads((cell / "card.json").read_text())
    assert cell_card["identity_id"] == "advanced-v6-commission"
    assert cell_card["soul_sha256"] == card["soul_sha256"]
