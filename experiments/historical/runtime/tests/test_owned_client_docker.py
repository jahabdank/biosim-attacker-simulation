"""Opt-in local Docker regression; no model, network, mounts or credentials."""

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import concurrent.futures
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pytest

STAGE = Path(__file__).resolve().parents[1]
RUNTIME = STAGE
sys.path[:0] = [str(STAGE / 'scripts/study'), str(RUNTIME / 'scripts/study'), str(RUNTIME / 'src')]
diagnostics = importlib.import_module('recovery_diagnostics')
base = importlib.import_module('run_next_batch')
assert Path(diagnostics.__file__).resolve() == STAGE / 'scripts/study/recovery_diagnostics.py'
assert base.ROOT == RUNTIME

pytestmark = pytest.mark.skipif(os.environ.get('NEXT46_LOCAL_DOCKER_TEST') != '1',
                                reason='Explicit disposable Docker test opt-in required')


def docker(*args, check=True):
    return subprocess.run(['docker', *args], text=True, capture_output=True, timeout=20, check=check)


def running(container):
    return docker('inspect', '--format', '{{.State.Running}}', container).stdout.strip() == 'true'


@pytest.mark.parametrize('trigger', ['fatal_diagnostics', 'timeout'])
def test_owned_client_real_docker_cleanup(tmp_path, trigger):
    image = docker('image', 'inspect', 'satml-grok-operator:v1', '--format', '{{.Id}}').stdout.strip()
    token = 'next46-client-test-' + uuid.uuid4().hex[:16]
    owned = token + '-operator'
    canary = token + '-canary'
    names = [owned, canary]
    ids = {}
    record = dict(trigger=trigger, image=image, names=names, model_calls=0)
    try:
        for name in names:
            ids[name] = docker('run', '-d', '--pull=never', '--name', name,
                '--label', 'next46-recovery-test=' + token, '--network', 'none',
                '--read-only', '--cap-drop=ALL', '--security-opt', 'no-new-privileges',
                '--pids-limit', '32', '--memory', '128m', '--cpus', '.25',
                '--user', '10001:10001', '--entrypoint', '/bin/sh', image,
                '-c', 'sleep 120 & wait').stdout.strip()
        assert running(ids[owned]) and running(ids[canary])
        canary_pid = docker('inspect', '--format', '{{.State.Pid}}', ids[canary]).stdout.strip()
        event_path = tmp_path / 'synthetic-route-diagnostics.jsonl'
        timeout = 20 if trigger == 'fatal_diagnostics' else 2
        command = ['docker', 'exec', ids[owned], '/bin/sh', '-c',
                   'printf "owned-before\\n"; printf "owned-error\\n" >&2; sleep 120 & wait']
        started = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(diagnostics.run_owned_client, command,
                container_id=ids[owned], timeout=timeout, diagnostics=event_path)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                top = docker('top', ids[owned], '-eo', 'pid,args').stdout
                if 'owned-before' in top:
                    break
                if future.done():
                    pytest.fail('Owned client exited before synthetic trigger')
                time.sleep(.05)
            else:
                pytest.fail('Owned sleeping exec did not start')
            if trigger == 'fatal_diagnostics':
                assert not event_path.exists() and not future.done()
                event_path.write_text('{"event":"transport_error","status":502}\n')
            triggered = time.monotonic()
            result = future.result(timeout=12)
        stopped = time.monotonic()
        assert result.returncode == 2
        assert result.stdout == 'owned-before\n'
        assert result.stderr == 'owned-error\n'
        assert stopped - triggered < 10
        assert not running(ids[owned])
        assert running(ids[canary])
        assert docker('inspect', '--format', '{{.State.Pid}}', ids[canary]).stdout.strip() == canary_pid
        assert docker('exec', ids[canary], '/bin/sh', '-c', 'printf canary-alive').stdout == 'canary-alive'
        record.update(elapsed_s=stopped - started, after_trigger_s=stopped - triggered,
                      returncode=result.returncode, stdout=result.stdout, stderr=result.stderr,
                      owned_stopped=True, canary_survived_same_pid=True, client_returned=True)
    finally:
        cleanup = []
        for name in names:
            inspection = docker('inspect', '--format', '{{index .Config.Labels "next46-recovery-test"}}', name, check=False)
            if inspection.returncode == 0:
                if inspection.stdout.strip() != token:
                    raise RuntimeError('Refusing cleanup of container without exact test label')
                docker('rm', '-f', name)
            cleanup.append(docker('inspect', name, check=False).returncode != 0)
        record['owned_test_containers_removed'] = all(cleanup)
        (STAGE / ('docker-' + trigger + '-result.json')).write_text(json.dumps(record, indent=2) + '\n')
        assert all(cleanup)
