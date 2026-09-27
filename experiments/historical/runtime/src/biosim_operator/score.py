"""Primary score is BioSim state, not an essay."""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


from dataclasses import asdict, dataclass
from typing import Any

from .habitat import HabitatView


@dataclass
class EpisodeScore:
    crew_alive: bool
    n_dead: int
    n_crew: int
    ticks: int
    hours: float
    simulation_ended: bool
    o2_fraction: float | None
    co2_fraction: float | None
    potable_water: float | None
    o2_store: float | None
    food: float | None
    uncleared_malfunctions: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_habitat(view: HabitatView) -> EpisodeScore:
    uncleared = 0
    for malf in view.malfunctions:
        if malf.get("performed") and not malf.get("doneEnoughRepairWork"):
            uncleared += 1

    if view.n_dead:
        reason = "crew_dead"
    elif view.simulation_ended:
        reason = "simulation_ended"
    else:
        reason = "horizon"

    return EpisodeScore(
        crew_alive=view.crew_alive and view.n_dead == 0,
        n_dead=view.n_dead,
        n_crew=len(view.crew),
        ticks=view.ticks,
        hours=view.ticks * view.tick_length,
        simulation_ended=view.simulation_ended,
        o2_fraction=view.o2_fraction,
        co2_fraction=view.co2_fraction,
        potable_water=view.store_level("Potable_Water_Store", "PotableWaterStore"),
        o2_store=view.store_level("O2_Store", "O2Store"),
        food=view.store_level("Food_Store", "FoodStore"),
        uncleared_malfunctions=uncleared,
        reason=reason,
    )
