"""Live BioSim: two board reads in one watch must not share a clock or a tank.

Skipped when the jar is missing. This is the proof the wrapper clock is
plant time, not a painted timestamp.
"""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


from pathlib import Path

import pytest

from biosim_operator.client import BioSimClient
from biosim_operator.habitat import operator_clock, parse_habitat, ticks_for_hours
from biosim_operator.plant import config_for
from biosim_operator.server import DEFAULT_JAR, BioSimServer

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def live_client():
    if not DEFAULT_JAR.is_file():
        pytest.skip(f"BioSim jar not at {DEFAULT_JAR}")
    server = BioSimServer(port=18009)
    server.start(wait_s=30)
    client = BioSimClient(server.base_url)
    try:
        yield client
    finally:
        server.stop()


def test_two_ticks_move_clock_and_oxygen_store(live_client: BioSimClient):
    xml = config_for("advanced", "stable").read_text()
    sim_id = live_client.start(xml)
    view0 = parse_habitat(live_client.snapshot(sim_id), sim_id=sim_id)
    assert abs(view0.tick_length - (1.0 / 60)) < 1e-6
    warmup = ticks_for_hours(2, view0.tick_length)
    live_client.advance_time(sim_id, warmup)
    epoch = "2026-08-20T19:12:59Z"

    a = parse_habitat(live_client.snapshot(sim_id), sim_id=sim_id)
    live_client.tick(sim_id)
    b = parse_habitat(live_client.snapshot(sim_id), sim_id=sim_id)

    clock_a = operator_clock(a.ticks, a.tick_length, epoch)
    clock_b = operator_clock(b.ticks, b.tick_length, epoch)
    assert clock_a is not None and clock_b is not None
    assert clock_a != clock_b
    assert b.ticks == a.ticks + 1
    # One minute of plant time.
    assert abs((b.ticks * b.tick_length) - (a.ticks * a.tick_length) - (1.0 / 60)) < 1e-6

    tank_a = a.store_level("O2_Store")
    tank_b = b.store_level("O2_Store")
    cabin_a = a.cabin_o2_moles
    cabin_b = b.cabin_o2_moles
    assert tank_a is not None and tank_b is not None
    assert cabin_a is not None and cabin_b is not None
    # OGS is filling the tank; crew are breathing. At least one of those
    # inventories must move. Identical IEEE floats would be a frozen plant.
    assert tank_a != tank_b or cabin_a != cabin_b


def test_four_hour_watch_is_240_minute_ticks(live_client: BioSimClient):
    xml = config_for("advanced", "stable").read_text()
    sim_id = live_client.start(xml)
    view = parse_habitat(live_client.snapshot(sim_id), sim_id=sim_id)
    assert ticks_for_hours(4, view.tick_length) == 240
    assert ticks_for_hours(24, view.tick_length) == 1440
