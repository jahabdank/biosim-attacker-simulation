
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import json
import os
import subprocess
import sys
from pathlib import Path
import pytest

from biosim_operator.server import BioSimServer, allocate_free_port

ROOT = Path(__file__).resolve().parents[1]
JAR = Path(str(_archive_path('path_028')))


def test_nonzero_operator_exit_stops_without_advancing(tmp_path):
    fake = tmp_path / 'error.py'
    fake.write_text('import sys\nprint("rate limited")\nsys.exit(1)\n')
    server = BioSimServer(jar=JAR,host='127.0.0.1',port=allocate_free_port())
    try:
        server.start(reuse_existing=False)
        env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'src');env.pop('FARSIDE_DOCKER',None)
        proc=subprocess.run([sys.executable,'-m','biosim_operator.cli_episode','--operator','mock','--mock-cmd',f'{sys.executable} {fake}','--mode','advanced','--stability','stable','--turns','2','--warmup-hours','0','--incomplete-on-timeout','--probe','none','--plant-url',server.base_url,'--artifact-dir',str(tmp_path/'episode')],cwd=ROOT,env=env,capture_output=True,text=True)
        assert proc.returncode==2,proc.stderr
        outcome=json.loads((tmp_path/'episode/outcome.json').read_text())
        assert outcome['incomplete_reason']=='operator_error'
        assert outcome['score']['ticks']==0
        assert not (tmp_path/'episode/wakes/02.json').exists()
    finally:
        server.stop()


def test_max_turn_exit_can_recover_watch_and_continue(tmp_path):
    fake = tmp_path / 'max_turn.py'
    fake.write_text(
        'import json,sys\n'
        'print(json.dumps({"session_id":"11111111-2222-3333-4444-555555555555"}))\n'
        'print("Error: max turns reached", file=sys.stderr)\n'
        'sys.exit(1)\n'
    )
    server = BioSimServer(jar=JAR,host='127.0.0.1',port=allocate_free_port())
    try:
        server.start(reuse_existing=False)
        env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'src');env.pop('FARSIDE_DOCKER',None)
        artifact=tmp_path/'episode'
        proc=subprocess.run([
            sys.executable,'-m','biosim_operator.cli_episode',
            '--operator','mock','--mock-cmd',f'{sys.executable} {fake}',
            '--mode','advanced','--stability','stable','--turns','2',
            '--ticks-per-turn','4','--warmup-hours','0',
            '--incomplete-on-timeout','--recover-max-turn-watch',
            '--max-tool-turns','32','--probe','none',
            '--plant-url',server.base_url,'--artifact-dir',str(artifact),
        ],cwd=ROOT,env=env,capture_output=True,text=True)
        assert proc.returncode==0,(proc.stdout[-2000:],proc.stderr[-2000:])
        outcome=json.loads((artifact/'outcome.json').read_text())
        assert outcome['status']=='complete'
        assert outcome['incomplete'] is False
        assert outcome['watch_cap_recoveries']==[1,2]
        # ticks_per_turn is expressed in simulated hours; the plant uses
        # one-minute ticks, so two four-hour watches advance 480 ticks.
        assert outcome['score']['ticks']==480
        wake1=json.loads((artifact/'wakes/01.json').read_text())
        wake2=json.loads((artifact/'wakes/02.json').read_text())
        assert wake1['watch_cap_recovered'] is True
        assert wake2['watch_cap_recovered'] is True
        assert 'previous watch closed' in wake2['query'].lower()
        assert 'new watch' in wake2['query'].lower()
        events=[json.loads(x) for x in (artifact/'transcript.jsonl').read_text().splitlines()]
        recovered=[e for e in events if e.get('event')=='watch_cap_recovered']
        assert [e['turn'] for e in recovered]==[1,2]
        setup=json.loads((artifact/'setup.json').read_text())
        assert setup['max_tool_turns']==32
        assert setup['recover_max_turn_watch'] is True
    finally:
        server.stop()


@pytest.mark.parametrize('diagnostic', [
    '{"event":"response","status":200}\n{"event":"stream_error","status":429}\n',
    '{"event":"stream_error","status":502}\n',
    '{"event":',
])
def test_success_exit_with_route_error_is_incomplete_without_advance(tmp_path, diagnostic):
    fake = tmp_path/'success.py'
    fake.write_text('print("success")\n')
    log = tmp_path/'route.jsonl'
    log.write_text(diagnostic)
    server = BioSimServer(jar=JAR, host='127.0.0.1', port=allocate_free_port())
    try:
        server.start(reuse_existing=False)
        env = os.environ.copy()
        env['PYTHONPATH'] = str(ROOT/'src')
        env['STUDY_ROUTE_DIAGNOSTICS'] = str(log)
        env.pop('FARSIDE_DOCKER', None)
        artifact = tmp_path/'episode'
        proc = subprocess.run([sys.executable, '-m', 'biosim_operator.cli_episode',
            '--operator', 'mock', '--mock-cmd', f'{sys.executable} {fake}',
            '--mode', 'advanced', '--stability', 'stable', '--turns', '2',
            '--warmup-hours', '0', '--incomplete-on-timeout', '--probe', 'none',
            '--plant-url', server.base_url, '--artifact-dir', str(artifact)],
            cwd=ROOT, env=env, capture_output=True, text=True)
        assert proc.returncode == 2
        outcome = json.loads((artifact/'outcome.json').read_text())
        assert outcome['incomplete_reason'] == 'route_error'
        assert outcome['score']['ticks'] == 0
        wake = json.loads((artifact/'wakes/01.json').read_text())
        assert wake['returncode'] != 0
        assert not (artifact/'wakes/02.json').exists()
    finally:
        server.stop()
