"""Episode loop: observe → (optional uplink) → decide → set_flow → advance many ticks.

One agent turn is not one BioSim tick. Default is 24 turns × 4 hours.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import BioSimClient
from .habitat import parse_habitat, ticks_for_hours
from .operators import Operator, apply_actions
from .score import EpisodeScore, score_habitat
from .uplink import UplinkBuffer


@dataclass
class TurnLog:
    turn: int
    ticks_before: int
    habitat: dict[str, Any]
    uplink_kind: str | None
    uplink_text: str | None
    actions: list[dict[str, Any]]
    apply_results: list[dict[str, Any]]
    ticks_after: int
    crew_alive: bool


@dataclass
class EpisodeResult:
    operator: str
    config: str
    sim_id: int
    n_turns: int
    ticks_per_turn: int
    score: EpisodeScore
    turns: list[TurnLog] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator": self.operator,
            "config": self.config,
            "sim_id": self.sim_id,
            "n_turns": self.n_turns,
            "ticks_per_turn": self.ticks_per_turn,
            "score": self.score.to_dict(),
            "turns": [
                {
                    "turn": t.turn,
                    "ticks_before": t.ticks_before,
                    "habitat": t.habitat,
                    "uplink_kind": t.uplink_kind,
                    "uplink_text": t.uplink_text,
                    "actions": t.actions,
                    "apply_results": t.apply_results,
                    "ticks_after": t.ticks_after,
                    "crew_alive": t.crew_alive,
                }
                for t in self.turns
            ],
        }


def run_episode(
    client: BioSimClient,
    xml_config: str,
    operator: Operator,
    *,
    n_turns: int = 24,
    ticks_per_turn: int = 4,
    use_uplink: bool = False,
    config_name: str = "",
    run_dir: Path | None = None,
) -> EpisodeResult:
    sim_id = client.start(xml_config)
    uplink = UplinkBuffer() if use_uplink else None
    turns: list[TurnLog] = []
    view = parse_habitat(client.snapshot(sim_id), sim_id=sim_id)

    for turn in range(1, n_turns + 1):
        if view.simulation_ended or view.all_dead:
            break
        before = view.to_operator_dict()
        ticks_before = view.ticks
        slot = uplink.next(view) if uplink else None
        actions = operator.decide(view, slot.text if slot else None)
        applied = apply_actions(client, sim_id, actions)
        ticks_after = client.advance_time(
            sim_id, ticks_for_hours(ticks_per_turn, view.tick_length)
        )
        view = parse_habitat(client.snapshot(sim_id), sim_id=sim_id)
        turns.append(
            TurnLog(
                turn=turn,
                ticks_before=ticks_before,
                habitat=before,
                uplink_kind=slot.kind if slot else None,
                uplink_text=slot.text if slot else None,
                actions=[
                    {"tool": a.tool, "args": a.args, "note": a.note} for a in actions
                ],
                apply_results=applied,
                ticks_after=ticks_after,
                crew_alive=view.crew_alive,
            )
        )

    result = EpisodeResult(
        operator=getattr(operator, "name", operator.__class__.__name__),
        config=config_name,
        sim_id=sim_id,
        n_turns=n_turns,
        ticks_per_turn=ticks_per_turn,
        score=score_habitat(view),
        turns=turns,
    )
    if run_dir is not None:
        run_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = run_dir / f"{stamp}_{result.operator}_sim{sim_id}.json"
        path.write_text(json.dumps(result.to_dict(), indent=2, default=str))
        (run_dir / "latest.txt").write_text(str(path))
    return result
