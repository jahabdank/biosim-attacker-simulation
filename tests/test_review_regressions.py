"""Independent-review regressions: domain fidelity, mutation integrity and treatment isolation."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest
from biosim_operator.client import BioSimClient, BioSimError
from biosim_operator.habitat import operator_equipment_type
from biosim_operator.uplink import compose_sband_frame as compose
from biosim_operator.manifest import load_manifest

ROOT = Path(__file__).resolve().parents[1]


def test_r1_all_xml_matches_source_derived_fixture():
    fixtures = json.loads((ROOT/'tests/fixtures/plant-domain.json').read_text())
    for name, expected in fixtures.items():
        data = (ROOT/'configs'/name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected['sha256']
        selectors = [[n.tag,n.get('moduleName'),n.get('generationType')] for n in ET.fromstring(data).iter() if n.get('generationType')]
        assert selectors == expected['selectors']
    assert operator_equipment_type('NuclearPowerPS') == 'nuclear_power'


def test_r3_lost_committed_tick_reply_is_not_replayed(monkeypatch):
    client = BioSimClient()
    state = {'ticks': 0, 'calls': 0}
    def lost(method, path, **kwargs):
        state['ticks'] += 240
        state['calls'] += 1
        raise BioSimError('synthetic lost acknowledgement')
    monkeypatch.setattr(client, '_request', lost)
    with pytest.raises(BioSimError, match='progress is unknown'):
        client.advance_time(1, 240)
    assert state == {'ticks':240,'calls':1}


@pytest.mark.parametrize('reply', [None, {}, {'ticks':240}, {'ticks':240,'advanced':239}, {'ticks':240,'advanced':True}])
def test_r3_incomplete_ack_does_not_fall_back(monkeypatch, reply):
    client = BioSimClient()
    calls = []
    monkeypatch.setattr(client, '_request', lambda *a, **k: calls.append(a) or reply)
    with pytest.raises(BioSimError):
        client.advance_time(1,240)
    assert sum(call[0] == 'POST' for call in calls) == 1
    assert len(calls) <= 2


@pytest.mark.parametrize('advanced', [0, 3])
def test_terminal_short_batch_uses_read_only_confirmation(monkeypatch, advanced):
    client=BioSimClient()
    calls=[]
    def request(method,path,**kwargs):
        calls.append(method)
        if method=='POST':
            return {'ticks':7,'advanced':advanced}
        return {'globals':{'simulationEnded':True,'ticksGoneBy':7}}
    monkeypatch.setattr(client,'_request',request)
    assert client.advance_time(1,10)==7
    assert calls==['POST','GET']


@pytest.mark.parametrize('state', [
    {'simulationEnded':False,'ticksGoneBy':7},
    {'simulationEnded':True,'ticksGoneBy':8},
    {'simulationEnded':'true','ticksGoneBy':7},
    {'simulationEnded':True,'ticksGoneBy':True},
])
def test_unverified_short_batch_never_repeats_mutation(monkeypatch,state):
    client=BioSimClient()
    calls=[]
    def request(method,path,**kwargs):
        calls.append(method)
        return {'ticks':7,'advanced':3} if method=='POST' else {'globals':state}
    monkeypatch.setattr(client,'_request',request)
    with pytest.raises(BioSimError,match='progress is unknown'):
        client.advance_time(1,10)
    assert calls==['POST','GET']


@pytest.mark.parametrize('error', [OSError, ValueError])
def test_terminal_confirmation_failure_never_repeats_mutation(monkeypatch,error):
    client=BioSimClient()
    calls=[]
    def request(method,path,**kwargs):
        calls.append(method)
        if method=='POST':
            return {'ticks':7,'advanced':3}
        raise error('synthetic confirmation failure')
    monkeypatch.setattr(client,'_request',request)
    with pytest.raises(BioSimError,match='progress is unknown'):
        client.advance_time(1,10)
    assert calls==['POST','GET']


def test_natural_simulator_stop_is_a_valid_short_batch():
    import os
    from biosim_operator.server import BioSimServer,DEFAULT_JAR,allocate_free_port

    jar=Path(os.environ.get('BIOSIM_JAR',str(DEFAULT_JAR)))
    if not jar.is_file():
        pytest.skip('BIOSIM_JAR required')
    xml=(ROOT/'configs/tight_cabin_stable.biosim').read_text()
    assert xml.count('<Globals ')==1 and 'runTillN=' not in xml
    xml=xml.replace('<Globals ','<Globals runTillN="3" ',1)
    xml=xml.replace('runTillCrewDeath="true"','runTillCrewDeath="false"',1)
    server=BioSimServer(jar=jar,host='127.0.0.1',port=allocate_free_port())
    try:
        server.start(reuse_existing=False)
        client=BioSimClient(server.base_url)
        sid=client.start(xml)
        assert client.advance_time(sid,10)==3
        state=client.snapshot(sid)['globals']
        assert state['simulationEnded'] is True and state['ticksGoneBy']==3
    finally:
        server.stop()


@pytest.mark.parametrize('separator', ['\n\n', '', '--- PEER MESSAGE ---', None])
def test_r5_manifest_separator_overrides_ambient(monkeypatch, tmp_path, separator):
    from biosim_operator import study
    from contextlib import contextmanager
    job = load_manifest(ROOT/'manifests/offline-control.json')['jobs'][0]
    job['sband_separator'] = separator
    captured = {}
    class Plant:
        def start(self): return 'http://127.0.0.1:1'
        def stop(self): pass
    class Process:
        pid = 12345
        returncode = 0
        def __init__(self, command, **kwargs): captured.update(command=command,env=kwargs['env'])
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def communicate(self,**kwargs): return ('','')
    monkeypatch.setattr(study,'OwnedPlant',Plant)
    monkeypatch.setattr(study.subprocess,'Popen',Process)
    monkeypatch.setenv('BIOSIM_SBAND_SEPARATOR','--- STALE AUTHORITY ---')
    monkeypatch.setenv('STUDY_FAKE_GROK',str(ROOT/'scripts/fake_grok.py'))
    study.launch_cli_episode(job,run_dir=tmp_path,container_grok=False)
    assert captured['env'].get('BIOSIM_SBAND_SEPARATOR') == separator
    if separator is not None:
        argv=captured['command']
        assert argv[argv.index('--sband-separator')+1] == separator


def test_r6_benign_controls_explicitly_use_original_neutral_channel():
    jobs=load_manifest(ROOT/'manifests/benign-controls.json')['jobs']
    for job in jobs:
        if job['probe'] != 'benign': continue
        assert job['envelope']=='neutral'
        assert job['sband_separator']=='\n\n--- additional text ---\n\n'
        assert compose('telemetry','benign instruction',separator=job['sband_separator'])=='telemetry\n\n--- additional text ---\n\nbenign instruction'


def test_r8_tmpfs_owner_matches_runtime_uid(monkeypatch, tmp_path):
    from biosim_operator import study_container as container
    monkeypatch.setattr(container,'OPERATOR_UID','23456:34567')
    monkeypatch.setenv('STUDY_FAKE_GROK',str(ROOT/'scripts/fake_grok.py'))
    argv=container.operator_security_argv(name='test',station=tmp_path,scratch=tmp_path,network='none')
    assert argv[argv.index('--user')+1]=='23456:34567'
    assert '/tmp:uid=23456,gid=34567,mode=700' in argv


def test_r3_remaining_watch_failure_records_unknown_progress(monkeypatch,tmp_path):
    import signal
    from biosim_operator import cli_episode, client, habitat
    state={'ticks':0,'calls':0}
    class Plant:
        def __init__(self,url): self.base_url=url
        def ping(self): return True
        def start(self,xml): return 1
        def snapshot(self,sim_id): return state['ticks']
        def advance_time(self,sim_id,count):
            state['ticks']+=count
            state['calls']+=1
            raise BioSimError('synthetic committed batch with lost response')
    def parse(tick,*,sim_id):
        crew=[habitat.CrewPersonView(name=str(i),activity='duty',alive=True,location='Labs') for i in range(4)]
        return habitat.HabitatView(sim_id=1,ticks=tick,tick_length=1/60,simulation_ended=False,run_till_crew_death=False,crew=crew,stores={},cabin_o2_moles=1,cabin_co2_moles=0,cabin_n2_moles=2,cabin_total_moles=3,cabin_volume=18000,light_intensity=0)
    monkeypatch.setattr(client,'BioSimClient',Plant)
    monkeypatch.setattr(habitat,'parse_habitat',parse)
    monkeypatch.setenv('BIOSIM_URL','http://127.0.0.1:1')
    monkeypatch.delenv('STUDY_ROUTE_DIAGNOSTICS',raising=False)
    fake=tmp_path/'success.py';fake.write_text('print("done")\n')
    previous=signal.getsignal(signal.SIGTERM)
    try:
        result=cli_episode.main(['--operator','mock','--mock-cmd',f'{sys.executable} {fake}','--mode','advanced','--stability','stable','--turns','2','--warmup-hours','0','--probe','none','--plant-url','http://127.0.0.1:1','--artifact-dir',str(tmp_path/'episode'),'--incomplete-on-timeout'])
    finally:
        signal.signal(signal.SIGTERM,previous)
    assert result==2 and state=={'ticks':240,'calls':1}
    outcome=json.loads((tmp_path/'episode/outcome.json').read_text())
    assert outcome['incomplete_reason']=='plant_error' and len(outcome['turns'])==1
    events=[json.loads(line) for line in (tmp_path/'episode/transcript.jsonl').read_text().splitlines()]
    assert any(e.get('plant_progress')=='unknown' for e in events)


def test_r4_barrier_waits_for_in_flight_panel_action(monkeypatch,tmp_path):
    import importlib.util
    import socket
    import threading
    import time
    spec=importlib.util.spec_from_file_location('settlement_broker',ROOT/'scripts/study/eclss_broker.py')
    broker=importlib.util.module_from_spec(spec);spec.loader.exec_module(broker)
    started=threading.Event();release=threading.Event();stopping=threading.Event();state=[]
    def action():
        started.set()
        assert release.wait(3)
        state.append('committed')
        return 'done'
    monkeypatch.setattr(broker,'_tools',lambda:{'set_flow':action})
    server=socket.socket(socket.AF_INET,socket.SOCK_STREAM);server.bind(('127.0.0.1',0));server.listen(16)
    def serve():
        try: broker._serve(server)
        except OSError:
            if not stopping.is_set(): raise
    worker=threading.Thread(target=serve,daemon=True);worker.start()
    request=socket.create_connection(server.getsockname());request.sendall(b'{"op":"call","name":"set_flow"}\n')
    assert started.wait(2)
    request.close()
    barrier=socket.create_connection(server.getsockname());barrier.sendall(b'{"op":"barrier"}\n');barrier.settimeout(.1)
    try:
        with pytest.raises(socket.timeout): barrier.recv(100)
        release.set();barrier.settimeout(3)
        assert json.loads(barrier.recv(100))=={'settled':True}
        assert state==['committed']
    finally:
        release.set();barrier.close();stopping.set();server.shutdown(socket.SHUT_RDWR);server.close();worker.join(3)
    assert not worker.is_alive()


@pytest.mark.parametrize('separator',['\n\n',''])
def test_r5_cli_distinguishes_explicit_blank_from_unspecified(tmp_path,separator):
    import os
    from biosim_operator.server import BioSimServer,DEFAULT_JAR,allocate_free_port
    jar=Path(os.environ.get('BIOSIM_JAR',str(DEFAULT_JAR)))
    if not jar.is_file(): pytest.skip('BIOSIM_JAR required')
    server=BioSimServer(jar=jar,host='127.0.0.1',port=allocate_free_port())
    fake=tmp_path/'success.py';fake.write_text('print("done")\n')
    try:
        server.start(reuse_existing=False)
        env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),BIOSIM_SBAND_SEPARATOR='--- STALE AUTHORITY ---')
        result=subprocess.run([sys.executable,'-m','biosim_operator.cli_episode','--operator','mock','--mock-cmd',f'{sys.executable} {fake}','--mode','advanced','--stability','stable','--turns','1','--warmup-hours','0','--probe','none','--plant-url',server.base_url,'--artifact-dir',str(tmp_path/'episode'),'--sband-separator',separator],env=env,capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stderr
        assert json.loads((tmp_path/'episode/room.json').read_text())['sband_separator']==separator
    finally:
        server.stop()
