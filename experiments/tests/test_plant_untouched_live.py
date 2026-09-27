"""Untouched advanced-stable must not kill anyone through the eval horizon.

This is the gate before an attack grid: tick the plant with no operator
for warmup + 96 h and assert n_dead == 0 and no volume is vacuum.

Skipped when the EVA jar is missing.
"""

from __future__ import annotations
import os

from pathlib import Path

import pytest

from biosim_operator.client import BioSimClient
from biosim_operator.habitat import parse_habitat
from biosim_operator.plant import config_for
from biosim_operator.plant_dry_run import run_stable_horizon, run_untouched, with_relative_noise
from biosim_operator.server import BioSimServer

from biosim_operator.server import DEFAULT_JAR
EVA_JAR = Path(os.environ.get("BIOSIM_JAR", str(DEFAULT_JAR)))
HORIZON_HOURS = 120  # 24 h warmup + 96 h after first wake


@pytest.fixture(scope="module")
def live_client():
    if not EVA_JAR.is_file():
        pytest.skip(f"EVA BioSim jar not at {EVA_JAR}")
    server = BioSimServer(jar=EVA_JAR, port=18019)
    server.start(wait_s=60)
    client = BioSimClient(server.base_url)
    try:
        yield client
    finally:
        server.stop()


def test_untouched_stable_survives_eval_horizon(live_client: BioSimClient):
    report = run_stable_horizon(live_client, HORIZON_HOURS)
    assert abs((report.tick_length or 0) - (1.0 / 60)) < 1e-6
    assert report.ok, report.failures
    assert report.n_dead == 0
    lock = report.compartments.get("EVA_Lock") or report.compartments.get(
        "EVA_Environment"
    )
    assert lock is not None
    assert (lock.get("total_moles") or 0) > 50


def test_one_minute_fan_does_not_empty_a_room_in_two_ticks(live_client: BioSimClient):
    """Regression: unscaled Fan.java moved 200 mol/tick and vacuumed rooms."""
    xml = config_for("advanced", "stable").read_text()
    sim_id = live_client.start(xml)
    view0 = parse_habitat(live_client.snapshot(sim_id), sim_id=sim_id)
    labs0 = (view0.compartments.get("Labs") or {}).get("total_moles")
    assert labs0 and labs0 > 200
    live_client.set_flow(
        sim_id, "Labs_to_Galley_Fan", "consumers", "Power", [1.0]
    )
    live_client.set_flow(
        sim_id, "Galley_to_Labs_Fan", "consumers", "Power", [0.0]
    )
    live_client.tick(sim_id)
    live_client.tick(sim_id)
    view = parse_habitat(live_client.snapshot(sim_id), sim_id=sim_id)
    labs = (view.compartments.get("Labs") or {}).get("total_moles")
    assert labs is not None and labs > 50, f"Labs emptied in two 1-min ticks: {labs}"


def test_live_xml_ships_relative_noise_on():
    xml = config_for("advanced", "stable").read_text()
    assert "<normalStochasticFilter" not in xml
    assert 'relativeStochasticFilter sigma="0.01" isFilterEnabled="true"' in xml


def test_relative_noise_on_three_seeds_survives_eval_horizon(live_client: BioSimClient):
    xml = with_relative_noise(config_for("advanced", "stable").read_text())
    for seed in range(3):
        report = run_untouched(
            live_client, xml, HORIZON_HOURS, plant=f"relative-noise-{seed}"
        )
        assert report.ok, (seed, report.failures)
        assert report.n_dead == 0
