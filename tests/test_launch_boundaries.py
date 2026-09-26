import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest
from biosim_operator import study
from biosim_operator.grok_harness import grok_bin
from biosim_operator.identity_pack import sha256_tree
from biosim_operator.study_container import operator_security_argv, inspect_operator_argv, validate_spec

ROOT = Path(__file__).resolve().parents[1]


def test_image_spec_contains_no_bundled_cli():
    assert validate_spec() == []
    assert 'COPY grok ' not in (ROOT/'docker/study/Dockerfile.grok').read_text()


def test_cli_is_explicit_mount_with_security_flags(monkeypatch, tmp_path):
    monkeypatch.setenv('STUDY_FAKE_GROK', str(ROOT/'scripts/fake_grok.py'))
    argv = operator_security_argv(name='synthetic', station=tmp_path/'station', scratch=tmp_path/'scratch', network='isolated')
    assert inspect_operator_argv(argv) == []
    assert any('dst=/usr/local/bin/grok,readonly' in item for item in argv)
    assert not any('docker.sock' in item for item in argv)


def test_live_gate_and_unknown_fake_fail_closed(monkeypatch):
    monkeypatch.delenv('BIOSIM_ALLOW_LIVE', raising=False)
    monkeypatch.delenv('STUDY_FAKE_GROK', raising=False)
    with pytest.raises(RuntimeError, match='disabled'):
        grok_bin()
    monkeypatch.setenv('STUDY_FAKE_GROK', '/arbitrary/executable')
    with pytest.raises(ValueError, match='bundled'):
        grok_bin()


@pytest.mark.parametrize('fake', [False, True])
@pytest.mark.parametrize('container', [False, True])
def test_host_interpreter_does_not_change_container_or_native_argv(monkeypatch, tmp_path, fake, container):
    from biosim_operator import grok_harness, study_container
    binary = ROOT/'scripts/fake_grok.py' if fake else tmp_path/'native-cli'
    if fake:
        monkeypatch.setenv('STUDY_FAKE_GROK', str(binary))
    else:
        binary.touch()
        monkeypatch.delenv('STUDY_FAKE_GROK', raising=False)
        monkeypatch.setenv('BIOSIM_ALLOW_LIVE', '1')
        monkeypatch.setenv('GROK_BIN', str(binary))
    calls = []
    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, '', '')
    monkeypatch.setattr(grok_harness.subprocess, 'run', run)
    monkeypatch.setattr(study_container, 'launch_or_block', lambda **kwargs: None)
    monkeypatch.setattr(study_container, 'run_grok_in_container', run)
    grok_harness.run_grok('watch', workspace=tmp_path, grok_home=tmp_path/'home',
                          resume=None, timeout=30, model='test-model', override='station',
                          native_subscription_only=not fake, container_grok=container)
    prefix = [sys.executable, str(binary)] if fake and not container else [str(binary)]
    assert calls[0][:len(prefix) + 1] == [*prefix, '--cwd']
    if container:
        inner = study_container.remap_grok_cmd_to_container(
            calls[0], host_workspace=tmp_path, host_home=tmp_path/'home')
        assert inner[:3] == [study_container.GROK_INSIDE, '--cwd', study_container.STATION_INSIDE]
        assert sys.executable not in inner


def test_host_launcher_with_unactivated_path(tmp_path):
    from biosim_operator.server import DEFAULT_JAR
    jar = Path(os.environ.get('BIOSIM_JAR', str(DEFAULT_JAR)))
    if not jar.is_file():
        pytest.skip('BIOSIM_JAR is required')
    path = tmp_path/'bin'
    path.mkdir()
    python = path/'python3'
    python.write_text('#!/bin/sh\necho "wrong PATH interpreter" >&2\nexit 97\n')
    python.chmod(0o755)
    manifest = json.loads((ROOT/'manifests/offline-control.json').read_text())
    manifest['jobs'][0].update(turns=2, warmup_hours=0, timeout=60)
    source = tmp_path/'manifest.json'
    source.write_text(json.dumps(manifest))
    output = tmp_path/'unactivated'
    env = dict(os.environ, PATH=f'{path}:/usr/bin:/bin', BIOSIM_JAR=str(jar),
               PYTHONDONTWRITEBYTECODE='1', BIOSIM_LOCK_DIR=str(tmp_path/'locks'))
    for key in ('VIRTUAL_ENV', 'BIOSIM_PLANT_IMAGE', 'BIOSIM_ALLOW_LIVE',
                'FAKE_HANG_WATCH', 'FAKE_FAILURE_WATCH', 'FAKE_CAP_WATCH'):
        env.pop(key, None)
    proc = subprocess.run([sys.executable, str(ROOT/'scripts/run_experiment.py'),
                           '--manifest', str(source), '--limit', '1', '--output', str(output)],
                          env=env, capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    episode = output/'0001/episode'
    outcome = json.loads((episode/'outcome.json').read_text())
    assert not outcome['incomplete'] and len(outcome['turns']) == 2
    assert json.loads((episode/'execution.json').read_text())['offline'] is True
    second = json.loads((episode/'wakes/02.stdout').read_text())
    assert second['history_length'] == 2 and second['cached_match'] is True
    assert json.loads((output/'status.json').read_text())['state'] == 'completed'


def test_identity_hash_is_not_self_referential(tmp_path):
    (tmp_path/'SOUL.md').write_text('synthetic identity')
    before = sha256_tree(tmp_path)
    (tmp_path/'pack.sha256').write_text(before)
    assert sha256_tree(tmp_path) == before


def test_cancel_targets_only_owned_process_groups(monkeypatch):
    calls = []
    monkeypatch.setattr(os, 'killpg', lambda pid, sig: calls.append((pid, sig)))
    try:
        study._CHILDREN.add(123456)
        study.cancel_active()
        assert calls == [(123456, signal.SIGTERM)]
        assert study._CANCELLED.is_set()
    finally:
        study._CHILDREN.clear()
        study._CANCELLED.clear()


def test_interrupted_launcher_cleans_owned_plant(tmp_path):
    from biosim_operator.server import DEFAULT_JAR
    from urllib.parse import urlsplit
    import socket
    jar = Path(os.environ.get('BIOSIM_JAR', str(DEFAULT_JAR)))
    if not jar.is_file():
        pytest.skip('BIOSIM_JAR is required')
    output = tmp_path/'cancelled'
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', BIOSIM_JAR=str(jar), FAKE_HANG_WATCH='1')
    manifest = json.loads((ROOT/'manifests/offline-control.json').read_text())
    manifest['jobs'][0].update(warmup_hours=0, turns=2)
    source = tmp_path/'fast-control.json'
    source.write_text(json.dumps(manifest))
    process = subprocess.Popen([sys.executable, str(ROOT/'scripts/run_experiment.py'),
                                '--manifest', str(source), '--output', str(output)],
                               env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        setup = output/'0001/episode/setup.json'
        deadline = time.monotonic() + 30
        while not setup.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.05)
        assert setup.exists()
        address = urlsplit(json.loads(setup.read_text())['biosim_url'])
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 2, (stdout, stderr)
        assert json.loads((output/'status.json').read_text())['state'] == 'interrupted'
        with socket.socket() as sock:
            sock.settimeout(1)
            assert sock.connect_ex((address.hostname, address.port)) != 0
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.communicate(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
