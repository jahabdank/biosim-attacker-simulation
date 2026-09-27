
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import concurrent.futures
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts/study'), str(ROOT / 'src')]
import run_next_recovery as recovery
import recovery_diagnostics as diagnostics
base = recovery.base


def manifest(model):
    jobs = [j for j in base.select_jobs() if j['model'] == model]
    controls = sorted(j['job_id'] for j in jobs if j['arm'] == 'control')
    return dict(model=model, jobs=jobs, gate=controls[0] if controls else None,
                concurrency=base.CAPS[model], timeout_s=900 if model == base.SONNET else 480,
                minimum_spacing_s=20 if model == base.SONNET else None, quota_window_s=60,
                max_attempts=len(jobs) + int(model == base.SONNET),
                technical_replacements={cell: 'old-' + cell for cell in controls})


def artifacts(job, path):
    path.mkdir(parents=True, exist_ok=True)
    common = dict(cell_id=job['job_id'], model=job['model'])
    recovery.save(path / 'card.json', common)
    recovery.save(path / 'outcome.json', dict(common, status='complete', incomplete=False,
        n_dead=0, n_crew=4, crew=[{'alive': True}] * 4, score={'hours': 120}))
    (path / 'transcript.jsonl').write_text('{"event":"turn"}\n')
    (path / 'wakes').mkdir(exist_ok=True)
    for n in range(1, 25):
        recovery.save(path / 'wakes' / f'{n:02}.json', dict(turn=n, returncode=0, timed_out=False))


def success(job, row):
    if job['model'] in {base.LUNA, base.SONNET}:
        (Path(row['attempt_root']) / 'route-diagnostics.jsonl').write_text('{"event":"response","status":200}\n')
    artifact = base.study.episode_dir(Path(row['attempt_root']), job['job_id'])
    artifacts(job, artifact)
    return dict(status='ok', artifact=str(artifact), returncode=0, usage={'total_tokens': 123})


@pytest.mark.parametrize('model', [base.LUNA, base.SONNET])
def test_gate_fanout_one_then_controls_then_attacks(model):
    m = manifest(model)
    ledger = dict(attempts=[])
    pending, cap = recovery.runnable(m, ledger)
    assert cap == 1 and [j['job_id'] for j in pending] == [m['gate']]
    ledger['attempts'].append(dict(job_id=m['gate'], status='running'))
    assert recovery.runnable(m, ledger)[0] == []
    ledger['attempts'][0]['status'] = 'ok'
    pending, cap = recovery.runnable(m, ledger)
    assert cap == base.CAPS[model]
    if model == base.LUNA:
        assert len(pending) == 2 and all(j['arm'] == 'control' for j in pending)
        ledger['attempts'].extend(dict(job_id=j['job_id'], status='ok') for j in pending)
    assert all(j['arm'] == 'attack' for j in recovery.runnable(m, ledger)[0])


def test_restart_completed_no_duplicate_calls(tmp_path, monkeypatch):
    m = manifest(base.SONNET)
    calls = []
    def execute(job, _, row):
        calls.append(job['job_id'])
        return success(job, row)
    monkeypatch.setattr(recovery, 'execute', execute)
    assert recovery.run_model(m, tmp_path)['state'] == 'completed'
    assert len(calls) == 10
    assert recovery.run_model(m, tmp_path)['state'] == 'completed'
    assert len(calls) == 10


def test_running_row_blocks_restart(tmp_path):
    m = manifest(base.SONNET)
    ledger = dict(attempts=[], state='running')
    recovery.admit(m, ledger, tmp_path, m['jobs'][0])
    with pytest.raises(RuntimeError, match='Interrupted'):
        recovery.run_model(m, tmp_path)


def test_lineage_and_duplicate_caps(tmp_path):
    m = manifest(base.LUNA)
    ledger = dict(attempts=[], state='running')
    job = next(j for j in m['jobs'] if j['job_id'] == m['gate'])
    row = recovery.admit(m, ledger, tmp_path, job)
    assert row['replacement_of'] == m['technical_replacements'][job['job_id']]
    row['status'] = 'incomplete'
    with pytest.raises(RuntimeError, match='Duplicate'):
        recovery.admit(m, ledger, tmp_path, job)
    row['replacement_of'] = 'wrong'
    with pytest.raises(RuntimeError, match='lineage'):
        recovery.check_ledger(m, ledger)


def test_one_quota_replacement_after_technical(tmp_path, monkeypatch):
    m = manifest(base.SONNET)
    ledger = dict(attempts=[], state='paused_quota')
    job = m['jobs'][0]
    failed = recovery.admit(m, ledger, tmp_path, job)
    failed.update(status='incomplete', quota_failure=True, retry_not_before=1)
    recovery.save(tmp_path / 'attempts.json', ledger)
    recovery.amend_quota(m, tmp_path)
    ledger = base.read_json(tmp_path / 'attempts.json')
    with pytest.raises(RuntimeError, match='cooldown'):
        recovery.admit(m, ledger, tmp_path, job, True)
    monkeypatch.setattr(recovery.time, 'time', lambda: ledger['quota_amendment']['not_before'] + 1)
    row = recovery.admit(m, ledger, tmp_path, job, True)
    assert row['replacement_of'] == failed['attempt_id'] and row['minimum_spacing_s'] == 65
    row.update(status='incomplete', quota_failure=True)
    ledger['state'] = 'paused_quota'
    recovery.save(tmp_path / 'attempts.json', ledger)
    with pytest.raises(RuntimeError, match='unused'):
        recovery.amend_quota(m, tmp_path)
    with pytest.raises(RuntimeError):
        recovery.admit(m, ledger, tmp_path, job, True)


@pytest.mark.parametrize('damage', ['exit', 'identity', 'wake', 'truncated', 'route', 'missing'])
def test_bad_success_rejected(tmp_path, damage):
    job = manifest(base.SONNET)['jobs'][0]
    artifact = tmp_path / 'episode'
    artifacts(job, artifact)
    row = dict(model=job['model'], artifact=str(artifact), returncode=0, attempt_root=str(tmp_path))
    if damage == 'exit':
        row['returncode'] = 2
    elif damage == 'identity':
        recovery.save(artifact / 'card.json', {'cell_id': 'wrong'})
    elif damage == 'wake':
        recovery.save(artifact / 'wakes/24.json', {'turn': 24, 'returncode': 1})
    elif damage == 'truncated':
        (artifact / 'transcript.jsonl').write_text('{')
    elif damage == 'route':
        (tmp_path / 'route-diagnostics.jsonl').write_text('{"status":429}\n')
    else:
        (artifact / 'outcome.json').unlink()
    with pytest.raises((RuntimeError, ValueError)):
        recovery.validate_success(job, row)


@pytest.mark.parametrize('text,active,reason', [
    ('{"status":', True, None), ('{"status":', False, 'diagnostic_parse_failure'),
    ('{broken}\n', True, 'diagnostic_parse_failure'), ('[]\n', True, 'diagnostic_parse_failure'),
    ('{"event":"client_disconnect"}\n', True, None),
    ('{"event":"request_error"}\n', True, None),
    ('{"event":"route_error"}\n', True, 'technical_failure'),
    ('{"event":"stream_error","status":429}\n', True, 'quota')])
def test_partial_and_classified_logs(tmp_path, text, active, reason):
    path = tmp_path / 'events'
    path.write_text(text)
    assert diagnostics.failure_reason(path, active=active) == reason


def test_model_local_pause(tmp_path, monkeypatch):
    def execute(job, _, row):
        return {'status': 'incomplete'} if job['model'] == base.SONNET else success(job, row)
    monkeypatch.setattr(recovery, 'execute', execute)
    dirs = {m: tmp_path / m for m in [base.SONNET, base.GROK]}
    for d in dirs.values():
        d.mkdir()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        futures = {m: pool.submit(recovery.run_model, manifest(m), d) for m, d in dirs.items()}
        assert futures[base.SONNET].result()['state'] == 'paused_technical_failure'
        assert futures[base.GROK].result()['state'] == 'completed'
    assert len(base.read_json(dirs[base.SONNET] / 'attempts.json')['attempts']) == 1


def test_failure_notification_before_drain(tmp_path, monkeypatch, capsys):
    entered, release = threading.Event(), threading.Event()
    m = manifest(base.GROK)
    def execute(job, _, row):
        root = Path(row['attempt_root'])
        (root / 'route-diagnostics.jsonl').write_text('{"status":502}\n')
        entered.set()
        assert release.wait(5)
        return {'status': 'incomplete'}
    monkeypatch.setattr(recovery, 'execute', execute)
    with concurrent.futures.ThreadPoolExecutor() as pool:
        task = pool.submit(recovery.run_model, m, tmp_path)
        assert entered.wait(2)
        import time
        deadline = time.monotonic() + 3
        output = ''
        while time.monotonic() < deadline:
            output += capsys.readouterr().out
            if 'FAILED' in output:
                break
            threading.Event().wait(.01)
        try:
            assert 'FAILED' in output
            assert not task.done()
        finally:
            release.set()
        assert task.result()['state'].startswith('paused')


def test_atomic_records(tmp_path):
    path = tmp_path / 'ledger.json'
    recovery.save(path, {'before': True})
    with pytest.raises(ValueError):
        recovery.save(path, {'bad': float('nan')})
    assert base.read_json(path) == {'before': True}
    assert list(tmp_path.iterdir()) == [path]


def test_freeze_requires_confirmation_before_writes(tmp_path):
    with pytest.raises(RuntimeError, match='confirmation'):
        recovery.freeze(tmp_path / 'new', tmp_path, [], False)
    assert not (tmp_path / 'new').exists()


def test_predecessor_locks_are_readonly_and_exclusive(tmp_path):
    paths = [tmp_path / 'runner.lock', *[tmp_path / m / 'model.lock' for m in base.CAPS]]
    for p in paths:
        p.parent.mkdir(exist_ok=True)
        p.write_text('historical')
    with recovery.predecessor_locks(tmp_path):
        with pytest.raises(BlockingIOError):
            with recovery.predecessor_locks(tmp_path):
                pass
    assert all(p.read_text() == 'historical' for p in paths)


def predecessor_fixture(tmp_path, monkeypatch):
    original = base.select_jobs()
    prior = tmp_path / 'prior.json'
    recovery.save(prior, {'state': 'completed', 'attempts': []})
    controls = {j['job_id'] for j in base.study.build_full_manifest()
                if j['model'] == base.GROK and j['arm'] == 'control' and j['repeat'] == 1}
    monkeypatch.setattr(base, 'completed_ids', lambda paths: controls)
    root = tmp_path / 'predecessor'
    root.mkdir()
    models, ledgers = {}, []
    for model in base.CAPS:
        directory = root / model
        directory.mkdir()
        jobs = [j for j in original if j['model'] == model]
        recovery.save(directory / 'manifest.json', {'jobs': jobs})
        models[model] = base.digest(directory / 'manifest.json')
        selected = jobs[:2] if model == base.GROK else [j for j in jobs if j['arm'] == 'control']
        rows = []
        for n, job in enumerate(selected):
            attempt = directory / 'attempts' / str(n)
            attempt.mkdir(parents=True)
            row = dict(attempt_id=model + str(n), job_id=job['job_id'], model=model,
                       status='incomplete', attempt_root=str(attempt), usage={'total_tokens': 12})
            if model == base.GROK:
                row.update(success(job, row))
            rows.append(row)
        path = directory / 'attempts.json'
        recovery.save(path, dict(state='paused_operator_request', attempts=rows))
        ledgers.append(path)
        recovery.save(directory / 'setup-failures-python-executable.json', {'attempts': []})
    recovery.save(root / 'setup-launch-amendment.json', {'excluded': 8})
    recovery.save(root / 'manifest.json', dict(models=models, archive={}, prior_ledgers={str(prior): base.digest(prior)}))
    return root, ledgers


def test_recovery_filters_only_valid_successes_and_retains_usage(tmp_path, monkeypatch):
    root, ledgers = predecessor_fixture(tmp_path, monkeypatch)
    plan = recovery.prepare_plan(root, ledgers)
    assert len(plan['successful_exclusions']) == 2
    assert sum(len(m['jobs']) for m in plan['models'].values()) == 44
    assert plan['original_jobs'] == base.select_jobs()
    assert len(plan['historical_attempts']) == 6
    assert all(r['usage']['total_tokens'] > 0 for r in plan['historical_attempts'])
    assert len(plan['amendment']['failed_attempts']) == 4
    assert plan['amendment']['inference_attempt_cap_including_predecessor'] == 51
    assert plan['models'][base.LUNA]['gate'] == sorted(plan['models'][base.LUNA]['technical_replacements'])[0]


@pytest.mark.parametrize('damage', ['running', 'missing-ledger', 'bad-artifact', 'selection'])
def test_predecessor_rejection(tmp_path, monkeypatch, damage):
    root, ledgers = predecessor_fixture(tmp_path, monkeypatch)
    if damage == 'running':
        ledger = base.read_json(ledgers[0])
        ledger['attempts'][0]['status'] = 'running'
        recovery.save(ledgers[0], ledger)
    elif damage == 'missing-ledger':
        ledgers.pop()
    elif damage == 'bad-artifact':
        ledger = base.read_json(root / base.GROK / 'attempts.json')
        (Path(ledger['attempts'][0]['artifact']) / 'card.json').write_text('{}')
    else:
        path = root / base.GROK / 'manifest.json'
        recovery.save(path, {'jobs': []})
        manifest = base.read_json(root / 'manifest.json')
        manifest['models'][base.GROK] = base.digest(path)
        recovery.save(root / 'manifest.json', manifest)
    with pytest.raises(RuntimeError):
        recovery.prepare_plan(root, ledgers)


def test_diagnostics_absent_during_startup_is_not_fatal(tmp_path, monkeypatch):
    assert diagnostics.failure_reason(tmp_path / 'not-created', active=True) is None
    def unexpected_stop(*args, **kwargs):
        pytest.fail('Startup without diagnostics must not stop a container')
    monkeypatch.setattr(diagnostics.subprocess, 'run', unexpected_stop)
    result = diagnostics.run_owned_client(
        [sys.executable, '-c', 'import time,sys; print("before",flush=True); time.sleep(.65); print("after"); print("err",file=sys.stderr)'],
        container_id='must-not-stop', timeout=5, diagnostics=tmp_path / 'not-created')
    assert result.returncode == 0 and result.stdout == 'before\nafter\n' and result.stderr == 'err\n'


def test_active_future_partial_log_becomes_terminal_failure(tmp_path):
    path = tmp_path / 'diagnostics'
    future = concurrent.futures.Future()
    path.write_text('{"status":')
    assert diagnostics.failure_reason(path, active=not future.done()) is None
    future.set_result(None)
    assert diagnostics.failure_reason(path, active=not future.done()) == 'diagnostic_parse_failure'
    path.write_text('{"status":200}\n')
    assert diagnostics.failure_reason(path, active=not future.done()) is None


def test_owned_child_exit_preserves_stdio(tmp_path):
    result = diagnostics.run_owned_client([sys.executable, '-c', 'print("owned child"); raise SystemExit(7)'],
        container_id='unused', timeout=5, diagnostics=tmp_path / 'absent')
    assert result.returncode == 7 and result.stdout.strip() == 'owned child'


def test_owned_client_stops_only_exact_container(tmp_path, monkeypatch):
    path = tmp_path / 'events'
    path.write_text('{"status":502}\n')
    calls = []
    class Child:
        returncode = -15
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def communicate(self, timeout=None):
            if not calls:
                raise subprocess.TimeoutExpired('owned', timeout)
            return 'partial-output', ''
    monkeypatch.setattr(diagnostics.subprocess, 'Popen', lambda *a, **k: Child())
    monkeypatch.setattr(diagnostics.subprocess, 'run', lambda cmd, **kw: calls.append(cmd) or SimpleNamespace(returncode=0))
    result = diagnostics.run_owned_client(['docker', 'exec'], container_id='exact-owned-id', timeout=10, diagnostics=path)
    assert calls == [['docker', 'stop', '--time', '2', 'exact-owned-id']]
    assert result.returncode == 2 and result.stdout == 'partial-output'
