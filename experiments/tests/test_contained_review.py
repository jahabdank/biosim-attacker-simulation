"""Opt-in real Docker regressions; no provider credentials or inference."""
import json
import os
from pathlib import Path
import subprocess
import time
import tempfile
import shutil
import uuid

import pytest
from biosim_operator import study_container as containment

ROOT=Path(__file__).resolve().parents[1]
pytestmark=pytest.mark.skipif(os.environ.get('BIOSIM_TEST_CONTAINERS')!='1',reason='Set BIOSIM_TEST_CONTAINERS=1 for real isolated Docker checks')


def test_r8_actual_operator_can_write_private_tmpfs(monkeypatch,tmp_path):
    monkeypatch.setenv('STUDY_FAKE_GROK',str(ROOT/'scripts/fake_grok.py'))
    station=tmp_path/'station';station.mkdir()
    scratch=tmp_path/'scratch';scratch.mkdir()
    argv=containment.operator_security_argv(name='eclss-tmp-'+uuid.uuid4().hex[:10],station=station,scratch=scratch,
        network='none',entrypoint='python3',detach=False,
        args=['-c','import os,tempfile; f=tempfile.TemporaryFile(dir="/tmp"); f.write(b"ok"); f.seek(0); assert f.read()==b"ok"; print(os.getuid())'])
    proc=subprocess.run(argv,capture_output=True,text=True,timeout=30)
    assert proc.returncode==0,proc.stderr
    assert proc.stdout.strip()==containment.OPERATOR_UID.split(':')[0]


@pytest.mark.parametrize('native',[False,True])
def test_r4_timeout_stops_daemon_exec_before_return(monkeypatch,tmp_path,native):
    binary=tmp_path/'synthetic-cli'
    binary.write_text('#!/usr/bin/env python3\nimport os,time\nfrom pathlib import Path\np=Path(os.environ["GROK_HOME"])/"counter"\nn=0\nwhile True:\n n+=1\n p.write_text(str(n))\n print("partial",flush=True)\n time.sleep(.03)\n')
    binary.chmod(0o755)
    monkeypatch.setenv('STUDY_FAKE_GROK',str(binary))
    monkeypatch.delenv('STUDY_ROUTE_DIAGNOSTICS',raising=False)
    seats=Path(tempfile.mkdtemp(prefix='eclss-r4-',dir='/tmp'))
    monkeypatch.setattr(containment,'STUDY_EPISODES',seats)
    station=ROOT/'packs/dual-alive-sband-t1-peer'
    log=tmp_path/'transcript.jsonl'
    session=containment.StudyContainment(episode_id=uuid.uuid4().hex[:12],station_src=station,
        plant_url='http://127.0.0.1:1',transcript_path=log)
    try:
        session.start()
        operator=session.operator_id
        if native:
            # Synthetic auth stands in for the file, never a user's subscription.
            session._native_subscription=True
            session._auth_copy=tmp_path/'synthetic-auth.json'
            session._auth_copy.write_text('{}')
        with pytest.raises(subprocess.TimeoutExpired) as stopped:
            session.run_grok(['grok','--tools',''],timeout=.5)
        assert 'partial' in stopped.value.output
        assert session.operator_id is None and session.relay_id is None
        assert session._panel_quiescent
        counter=session.paths['scratch']/'grok-home/counter'
        final=counter.read_text()
        time.sleep(.15)
        assert counter.read_text()==final
        inspect=subprocess.run(['docker','inspect',operator],capture_output=True,text=True)
        assert inspect.returncode!=0
        assert json.loads(log.read_text().splitlines()[-1])['panel_settled'] is True
    finally:
        session.stop()
        shutil.rmtree(seats)
