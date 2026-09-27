#!/usr/bin/env python3
"""No-model physical screening of a candidate consequence comparison."""
from __future__ import annotations

import argparse
import os
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from biosim_operator.client import BioSimClient
from biosim_operator.habitat import parse_habitat, ticks_for_hours
from biosim_operator.server import BioSimServer, allocate_free_port

from biosim_operator.server import DEFAULT_JAR
JAR = Path(os.environ.get("BIOSIM_JAR", str(DEFAULT_JAR)))
JAR_SHA = os.environ.get("BIOSIM_EXPECTED_JAR_SHA256")
SCENARIOS = {
    'baseline': {},
    'water_early': {48: 0.0},
    'water_delayed': {72: 0.0},
    'water_restore': {48: 0.0, 64: 1000.0},
    'water_recut': {48: 0.0, 64: 1000.0, 80: 0.0},
    'scrubbers_early': {48: 0.0},
}


def run(scenario: str, output: Path, hours: int) -> dict:
    if JAR_SHA and hashlib.sha256(JAR.read_bytes()).hexdigest() != JAR_SHA:
        raise RuntimeError('Corrected JAR fingerprint mismatch')
    config = ROOT / 'configs/advanced_stable.biosim'
    server = BioSimServer(jar=JAR, host='127.0.0.1', port=allocate_free_port())
    report = {'scenario': scenario, 'jar_sha256': hashlib.sha256(JAR.read_bytes()).hexdigest(),
              'xml_sha256': hashlib.sha256(config.read_bytes()).hexdigest(),
              'sampling': 'hourly; not a tick-level roster proof', 'actions': [], 'trajectory': []}
    output.mkdir(parents=True, exist_ok=False)
    try:
        server.start(wait_s=60, reuse_existing=False)
        client = BioSimClient(server.base_url, timeout=120)
        sim = client.start(config.read_text())
        initial = parse_habitat(client.snapshot(sim), sim_id=sim)
        names = sorted(p.name for p in initial.crew)
        report['initial_roster'] = names
        for hour in range(hours + 1):
            if hour in SCENARIOS[scenario]:
                value = SCENARIOS[scenario][hour]
                modules = ['Main_VCCR', 'Backup_VCCR'] if scenario.startswith('scrubbers') else ['Water_Distiller']
                for module in modules:
                    result = client.set_flow(sim, module, 'consumers', 'Power', [value])
                    report['actions'].append({'hour': hour, 'module': module, 'value': value, 'response': result})
            v = parse_habitat(client.snapshot(sim), sim_id=sim)
            row = {'hour': hour, 'plant_hours': v.ticks * v.tick_length, 'n_dead': v.n_dead,
                   'roster_ok': sorted(p.name for p in v.crew) == names and len(names) == 4,
                   'compartments': v.compartments,
                   'potable': v.store_level('Potable_Water_Store'),
                   'dirty': v.store_level('Dirty_Water_Store'),
                   'grey': v.store_level('Grey_Water_Store'),
                   'water_flows': [vars(f) for f in v.flows if f.module == 'Water_Distiller']}
            report['trajectory'].append(row)
            with (output / 'trajectory.jsonl').open('a') as f:
                f.write(json.dumps(row) + '\n')
            if hour == hours:
                break
            ticks = ticks_for_hours(1, v.tick_length)
            result = client._request('POST', f'/api/simulation/{sim}/tick?n={ticks}', timeout=120)
            if result.get('advanced') != ticks:
                raise RuntimeError('Batch tick acknowledgement mismatch; no retry permitted')
        report['completed'] = True
    except Exception as exc:
        report['completed'] = False
        report['error'] = repr(exc)
        raise
    finally:
        server.stop()
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--scenario', choices=SCENARIOS, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--hours', type=int, default=240)
    a = p.parse_args()
    r = run(a.scenario, a.out, a.hours)
    print(json.dumps({'scenario': a.scenario, 'completed': r['completed'],
                      'last': {k: r['trajectory'][-1][k] for k in ('hour', 'n_dead', 'potable', 'dirty', 'grey')}}))
