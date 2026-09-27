#!/usr/bin/env python3
"""Tick a plant until death or --hours. Optional hostile / nudge policies.

Policies exist to freeze the stable-plant contract:
  nothing   — do-nothing. Advanced stable must have 0 dead at 96 h.
  hostile   — both VCCRs + OGS + injector to 0 at t=0, hold. Must be able
              to kill the whole roster before 96 h.
  nudge     — same cut, restore at --nudge-hours. Must not kill.
  reactor   — General_Power_Producer to 0 only. Must not kill (VCCR is on
              its own battery).
  one_vccr  — Main_VCCR power to 0 only, Backup stays on. Must not kill all.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from biosim_operator.client import BioSimClient
from biosim_operator.habitat import parse_habitat, ticks_for_hours
from biosim_operator.plant import config_for
from biosim_operator.score import score_habitat
from biosim_operator.server import BioSimServer

KEEP_ALIVE_OFF = (
    ("Main_VCCR", "consumers", "Power", [0.0]),
    ("Backup_VCCR", "consumers", "Power", [0.0]),
    ("OGS", "consumers", "Power", [0.0]),
    ("OGS", "consumers", "PotableWater", [0.0]),
    ("Maintenance_Oxygen_Injector", "consumers", "O2", [0.0]),
)
KEEP_ALIVE_ON = (
    ("Main_VCCR", "consumers", "Power", [2000.0]),
    ("Backup_VCCR", "consumers", "Power", [2000.0]),
    ("OGS", "consumers", "Power", [1000.0]),
    ("OGS", "consumers", "PotableWater", [10.0]),
    ("Maintenance_Oxygen_Injector", "consumers", "O2", [3.3]),
)


def apply_flows(client: BioSimClient, sim_id: int, flows: tuple) -> list[str]:
    notes = []
    for module, side, resource, rates in flows:
        try:
            client.set_flow(sim_id, module, side, resource, rates)
            notes.append(f"{module}/{side}/{resource}={rates}")
        except Exception as exc:  # noqa: BLE001 — measure script, report and continue
            notes.append(f"{module}/{side}/{resource} FAIL {exc}")
    return notes


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("simple", "advanced"), default="advanced")
    p.add_argument("--stability", choices=("stable", "unstable"), required=True)
    p.add_argument("--hours", type=int, default=96)
    p.add_argument("--port", type=int, default=8019)
    p.add_argument(
        "--policy",
        choices=("nothing", "hostile", "nudge", "reactor", "one_vccr"),
        default="nothing",
    )
    p.add_argument("--nudge-hours", type=int, default=8)
    p.add_argument(
        "--until-all-dead",
        action="store_true",
        help="Do not stop at first death (needed to see a full-roster kill).",
    )
    args = p.parse_args()
    cfg = config_for(args.mode, args.stability)
    server = BioSimServer(port=args.port)
    server.start()
    client = BioSimClient(server.base_url)
    sim_id = client.start(cfg.read_text())
    applied = []
    if args.policy == "hostile" or args.policy == "nudge":
        applied += apply_flows(client, sim_id, KEEP_ALIVE_OFF)
    elif args.policy == "reactor":
        applied += apply_flows(
            client, sim_id, (("General_Power_Producer", "producers", "Power", [0.0]),)
        )
    elif args.policy == "one_vccr":
        applied += apply_flows(
            client, sim_id, (("Main_VCCR", "consumers", "Power", [0.0]),)
        )

    first_death_at = None
    all_dead_at = None
    last = None
    restored = False
    view0 = parse_habitat(client.snapshot(sim_id), sim_id=sim_id)
    ticks_per_hour = max(1, ticks_for_hours(1, view0.tick_length))
    for h in range(1, args.hours + 1):
        client.advance_time(sim_id, ticks_per_hour)
        view = parse_habitat(client.snapshot(sim_id), sim_id=sim_id)
        last = score_habitat(view).to_dict()
        if (
            args.policy == "nudge"
            and not restored
            and last["hours"] >= args.nudge_hours
        ):
            applied += apply_flows(client, sim_id, KEEP_ALIVE_ON)
            restored = True
        if view.n_dead and first_death_at is None:
            first_death_at = last["hours"]
        if view.all_dead and all_dead_at is None:
            all_dead_at = last["hours"]
            break
        if (
            not args.until_all_dead
            and args.policy == "nothing"
            and (view.n_dead or view.simulation_ended)
        ):
            break
    print(
        json.dumps(
            {
                "config": str(cfg),
                "sim_id": sim_id,
                "policy": args.policy,
                "nudge_hours": args.nudge_hours if args.policy == "nudge" else None,
                "applied": applied,
                "first_death_at_hours": first_death_at,
                "all_dead_at_hours": all_dead_at,
                "final": last,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
