#!/usr/bin/env python3
"""US-1 smoke: start, snapshot fields, tick, set_flow, confirm crew-death is readable."""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from biosim_operator.client import BioSimClient
from biosim_operator.habitat import parse_habitat
from biosim_operator.server import BioSimServer


def main() -> int:
    server = BioSimServer()
    server.start()
    client = BioSimClient(server.base_url)

    default_xml = (ROOT / "configs" / "default_paused.biosim").read_text()
    sim_id = client.start(default_xml)
    snap0 = client.snapshot(sim_id)
    view0 = parse_habitat(snap0, sim_id=sim_id)
    print("=== US-1 snapshot (default_paused) ===")
    print(json.dumps(view0.to_operator_dict(), indent=2, default=str))
    print("module_types:", sorted({m.get("moduleType") for m in (snap0.get("modules") or {}).values()}))
    print("store_names:", sorted(view0.stores))

    ticks = client.advance_time(sim_id, 2)
    view1 = parse_habitat(client.snapshot(sim_id), sim_id=sim_id)
    print(f"ticked to {ticks}; O2 moles {view0.cabin_o2_moles} -> {view1.cabin_o2_moles}")
    if view1.ticks <= view0.ticks:
        print("FAIL: tick did not advance")
        return 1

    # Tight cabin: prove set_flow moves a set-point and crew-death is readable.
    tight = (ROOT / "configs" / "tight_cabin.biosim").read_text()
    tight_id = client.start(tight)
    before = parse_habitat(client.snapshot(tight_id), tight_id)
    client.set_flow(tight_id, "O2_Injector", "consumers", "O2", [5.0])
    after_set = parse_habitat(client.snapshot(tight_id), tight_id)
    inj = [f for f in after_set.flows if f.module == "O2_Injector" and f.resource == "O2"]
    print("injector flows after set:", [(f.side, f.desired) for f in inj])
    if not any(f.side == "consumers" and f.desired and f.desired[0] == 5.0 for f in inj):
        print("FAIL: set_flow did not stick")
        return 1

    # Close the tank valve + run until death or 40 ticks — death must be a state flag.
    client.set_flow(tight_id, "O2_Injector", "consumers", "O2", [0.0])
    death_tick = None
    view = after_set
    for _ in range(40):
        client.tick(tight_id)
        view = parse_habitat(client.snapshot(tight_id), tight_id)
        if (not view.crew_alive) or view.simulation_ended:
            death_tick = view.ticks
            break
    print(
        "crew-death readable:",
        {
            "ticks": view.ticks,
            "crew_alive": view.crew_alive,
            "n_dead": view.n_dead,
            "activities": [p.activity for p in view.crew],
            "simulation_ended": view.simulation_ended,
            "death_tick": death_tick,
        },
    )
    if view.crew_alive and not view.simulation_ended:
        print("WARN: crew still alive after 40 closed-cabin hours (room may be too easy)")
    else:
        print("OK: crew-death is a sim end-state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
