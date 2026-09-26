
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/study"))
spec = importlib.util.spec_from_file_location("next_batch", ROOT / "scripts/study/run_next_batch.py")
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


def manifest(model):
    return {"model": model, "jobs": [j for j in batch.select_jobs() if j["model"] == model],
            "concurrency": batch.CAPS[model], "timeout_s": 900 if model == batch.SONNET else 480,
            "minimum_spacing_s": 20 if model == batch.SONNET else None,
            "replacement_spacing_s": 65, "quota_window_s": 60,
            "max_replacements": int(model == batch.SONNET),
            "max_attempts": batch.COUNTS[model] + int(model == batch.SONNET)}


def artifacts(job, directory, *, dead=0, hours=120, watches=24):
    directory.mkdir(parents=True, exist_ok=True)
    common = {"cell_id": job["job_id"], "model": job["model"]}
    (directory / "card.json").write_text(json.dumps(common))
    (directory / "outcome.json").write_text(json.dumps(dict(common, status="complete", incomplete=False,
        n_dead=dead, n_crew=4, crew=[{"alive": i >= dead} for i in range(4)], score={"hours": hours})))
    (directory / "transcript.jsonl").write_text('{"event":"test"}\n')
    (directory / "wakes").mkdir(exist_ok=True)
    for n in range(1, watches + 1):
        (directory / "wakes" / f"{n:02}.json").write_text(json.dumps({"turn": n, "returncode": 0, "timed_out": False}))


def test_selection_exact_repeats_and_exclusions():
    from run_first_batch import select_jobs
    previous = {j["job_id"] for j in select_jobs() if j["model"] != batch.SONNET}
    jobs = batch.select_jobs(previous)
    assert len(jobs) == len({j["job_id"] for j in jobs}) == 46
    for j in jobs:
        if j["model"] == batch.SONNET:
            assert j["repeat"] == 1 and (j["arm"] == "attack" or j["trust"] == "t1")
        elif j["model"] == batch.GROK:
            assert j["trust"] in {"t1", "t2"}
            assert j["repeat"] in ({3, 4, 5} if j["arm"] == "attack" else {2})
        else:
            assert j["repeat"] == (3 if j["arm"] == "attack" else 2)
    with pytest.raises(RuntimeError, match="already completed"):
        batch.select_jobs({jobs[0]["job_id"]})


def test_timeout_environment_forwarding(tmp_path, monkeypatch):
    m = manifest(batch.SONNET)
    job = m["jobs"][0]
    ledger = {"attempts": []}
    row = batch.admit(m, ledger, tmp_path, job)
    def launch(job, **kwargs):
        assert kwargs["extra_argv"] == ["--timeout", "900"]
        assert kwargs["env"]["STUDY_SONNET_MIN_SPACING_S"] == "20.0"
        assert kwargs["env"]["STUDY_SONNET_PACING"] == "1"
        assert kwargs["env"]["STUDY_ROUTE_DIAGNOSTICS"].endswith("route-diagnostics.jsonl")
        artifacts(job, batch.study.episode_dir(kwargs["run_dir"], job["job_id"]))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(batch.study, "launch_cli_episode", launch)
    monkeypatch.setattr(batch.study, "collect_attempt_usage", lambda p: {})
    assert batch.execute(job, m, row)["status"] == "ok"
    env = batch.attempt_env(manifest(batch.LUNA), tmp_path, None)
    assert "STUDY_SONNET_PACING" not in env


@pytest.mark.parametrize('model,enabled', [(batch.GROK, False), (batch.LUNA, True), (batch.SONNET, True)])
def test_diagnostics_only_for_broker_models(tmp_path, monkeypatch, model, enabled):
    monkeypatch.setenv('STUDY_ROUTE_DIAGNOSTICS', str(tmp_path/'inherited-missing.jsonl'))
    env = batch.attempt_env(manifest(model), tmp_path, 20 if model == batch.SONNET else None)
    assert ('STUDY_ROUTE_DIAGNOSTICS' in env) is enabled
    if enabled:
        assert env['STUDY_ROUTE_DIAGNOSTICS'] == str(tmp_path/'route-diagnostics.jsonl')


def test_mocked_native_episode_without_route_diagnostics(tmp_path, monkeypatch):
    import subprocess
    from biosim_operator.server import BioSimServer, allocate_free_port
    jar = batch.study.EVA_JAR
    if not jar.is_file():
        pytest.skip('EVA jar unavailable')
    monkeypatch.setenv('STUDY_ROUTE_DIAGNOSTICS', str(tmp_path/'inherited-missing.jsonl'))
    env = batch.attempt_env(manifest(batch.GROK), tmp_path, None)
    env['PYTHONPATH'] = str(ROOT/'src')
    env.pop('FARSIDE_DOCKER', None)
    assert 'STUDY_ROUTE_DIAGNOSTICS' not in env
    fake = tmp_path/'native-success.py'
    fake.write_text('print("mocked native success")\n')
    artifact = tmp_path/'episode'
    server = BioSimServer(jar=jar, host='127.0.0.1', port=allocate_free_port())
    try:
        server.start(reuse_existing=False)
        proc = subprocess.run([sys.executable, '-m', 'biosim_operator.cli_episode',
            '--operator', 'mock', '--model', batch.GROK,
            '--mock-cmd', f'{sys.executable} {fake}', '--mode', 'advanced',
            '--stability', 'stable', '--turns', '2', '--ticks-per-turn', '1',
            '--warmup-hours', '0', '--incomplete-on-timeout', '--probe', 'none',
            '--plant-url', server.base_url, '--artifact-dir', str(artifact)],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=90)
        assert proc.returncode == 0
        outcome = batch.read_json(artifact/'outcome.json')
        assert outcome['status'] == 'complete' and not outcome['incomplete']
        assert outcome['score']['ticks'] > 0
        assert batch.read_json(artifact/'wakes/02.json')['returncode'] == 0
        assert not (tmp_path/'route-diagnostics.jsonl').exists()
    finally:
        server.stop()


def test_terminal_and_missing_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(batch.study, "collect_attempt_usage", lambda p: {})
    attack = next(j for j in batch.select_jobs() if j["arm"] == "attack")
    assert batch.inspect_artifacts(attack, tmp_path, 0)["status"] == "missing_artifact"
    artifacts(attack, tmp_path, dead=4, hours=72, watches=12)
    assert batch.inspect_artifacts(attack, tmp_path, 0)["status"] == "ok"
    artifacts(attack, tmp_path, dead=1, hours=72, watches=12)
    assert batch.inspect_artifacts(attack, tmp_path, 0)["status"] != "ok"
    control = next(j for j in batch.select_jobs() if j["arm"] == "control")
    artifacts(control, tmp_path, dead=4, hours=72, watches=12)
    assert "control_survival" in batch.inspect_artifacts(control, tmp_path, 0)["validation_errors"]


def test_local_gate_and_pause_do_not_affect_other_model(tmp_path, monkeypatch):
    sonnet = manifest(batch.SONNET)
    luna = manifest(batch.LUNA)
    seen = []
    def execute(job, m, row):
        seen.append((job["model"], job["arm"]))
        return {"status": "incomplete" if job["model"] == batch.SONNET else "ok"}
    monkeypatch.setattr(batch, "execute", execute)
    for model, m in [(batch.SONNET, sonnet), (batch.LUNA, luna)]:
        d = tmp_path / model
        d.mkdir()
        result = batch.run_model(m, d)
        assert result["state"] == ("paused_technical_failure" if model == batch.SONNET else "completed")
    assert [arm for model, arm in seen if model == batch.SONNET] == ["control"]
    assert [arm for model, arm in seen if model == batch.LUNA][:3] == ["control"] * 3


def test_restart_refuses_running_or_duplicate(tmp_path):
    m = manifest(batch.SONNET)
    ledger = {"attempts": [], "state": "running"}
    batch.admit(m, ledger, tmp_path, m["jobs"][0])
    with pytest.raises(RuntimeError, match="Interrupted"):
        batch.check_ledger(m, ledger)
    with pytest.raises(RuntimeError, match="Duplicate"):
        batch.admit(m, ledger, tmp_path, m["jobs"][0])


def test_single_explicit_replacement_retains_failure(tmp_path, monkeypatch):
    m = manifest(batch.SONNET)
    ledger = {"attempts": [], "state": "paused_quota"}
    clock = [1000.0]
    monkeypatch.setattr(batch.time, "time", lambda: clock[0])
    failed = batch.admit(m, ledger, tmp_path, m["jobs"][0])
    (Path(failed["attempt_root"]) / "failure.json").write_text('{"status":429}')
    failed.update(status="incomplete", quota_failure=True, retry_not_before=1100)
    batch.amend(m, ledger, tmp_path)
    with pytest.raises(RuntimeError, match="cooldown"):
        batch.admit(m, ledger, tmp_path, m["jobs"][0], failed)
    clock[0] = 1101
    replacement = batch.admit(m, ledger, tmp_path, m["jobs"][0], failed)
    assert replacement["minimum_spacing_s"] == 65
    assert replacement["attempt_root"] != failed["attempt_root"]
    assert (Path(failed["attempt_root"]) / "failure.json").exists()
    replacement.update(status="incomplete", quota_failure=True)
    ledger["state"] = "paused_quota"
    with pytest.raises(RuntimeError, match="Only one"):
        batch.amend(m, ledger, tmp_path)
    with pytest.raises(RuntimeError, match="cap"):
        batch.admit(m, ledger, tmp_path, m["jobs"][0], failed)
    batch.check_ledger(m, ledger)


def test_exclusive_lock(tmp_path):
    with batch.exclusive(tmp_path / "runner.lock"):
        with pytest.raises(BlockingIOError):
            with batch.exclusive(tmp_path / "runner.lock"):
                pass


def test_quota_detection_retry_after(tmp_path, monkeypatch):
    m = manifest(batch.SONNET)
    ledger = {"attempts": []}
    row = batch.admit(m, ledger, tmp_path, m["jobs"][0])
    root = Path(row["attempt_root"])
    (root / "route-diagnostics.jsonl").write_text(json.dumps({"event": "response", "status": 429, "at": 100, "retry_after_s": 180}) + "\n")
    monkeypatch.setattr(batch.study, "launch_cli_episode", lambda *a, **k: SimpleNamespace(returncode=2))
    result = batch.execute(m["jobs"][0], m, row)
    assert result["quota_failure"] and result["status"] == "incomplete"
    assert result["retry_not_before"] == 280


def test_freeze_verify_and_archive_tamper(tmp_path, monkeypatch):
    from run_first_batch import select_jobs
    ids = {j['job_id'] for j in select_jobs() if j['model'] != batch.SONNET}
    prior = tmp_path / 'prior.json'
    prior.write_text('{}')
    monkeypatch.setattr(batch, 'completed_ids', lambda *a, **k: ids)
    monkeypatch.setattr(batch.study, 'collect_fingerprints', lambda: {'docker_images': {'available': True, 'images': {'plant': {'present': True}}}})
    monkeypatch.setattr(batch, 'verify_runtime', lambda m: None)
    destination = tmp_path / 'next46.mock'
    batch.freeze(destination, [prior], 20)
    assert len(batch.verify(destination)) == 3
    assert (destination/'frozen-inputs/scripts/study/run_next_batch.py').is_file()
    with pytest.raises(RuntimeError, match='fresh'):
        batch.freeze(destination, [prior], 20)
    (destination/'frozen-inputs/scripts/study/run_next_batch.py').write_text('changed')
    with pytest.raises(RuntimeError, match='archive changed'):
        batch.verify(destination)


def test_launch_helper_preserves_config_and_unique_runtime(tmp_path, monkeypatch):
    from biosim_operator import study
    observed = []
    class Plant:
        port = 12345
        def start(self):
            return _archive_setting('endpoint_046')
        def stop(self):
            pass
    monkeypatch.setattr(study, 'OwnedPlant', Plant)
    def run(argv, **kwargs):
        observed.append((argv, kwargs['env']))
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(study.subprocess, 'run', run)
    m = manifest(batch.SONNET)
    for i in range(2):
        root = tmp_path / str(i)
        study.launch_cli_episode(m['jobs'][0], run_dir=root,
            env=batch.attempt_env(m, root, 20), extra_argv=['--timeout', '900'])
    ids = []
    for argv, env in observed:
        assert argv[argv.index('--timeout', argv.index('--timeout') + 1) + 1] == '900'
        assert env['STUDY_SONNET_MIN_SPACING_S'] == '20.0'
        assert 'ROUTE_A_HARNESS_API_KEY' not in env
        ids.append(argv[argv.index('--run-id') + 1])
    assert ids[0] != ids[1]


def test_model_route_inherits_pacing_without_container_secret(monkeypatch, tmp_path):
    from biosim_operator import study_container
    monkeypatch.setenv('STUDY_SONNET_MIN_SPACING_S', '20')
    monkeypatch.setenv('STUDY_SONNET_PACING', '1')
    monkeypatch.setenv('STUDY_ROUTE_DIAGNOSTICS', str(tmp_path/'diagnostics.jsonl'))
    instance = object.__new__(study_container.StudyContainment)
    instance.paths = {'root':tmp_path, 'logs':tmp_path/'logs', 'scratch':tmp_path/'scratch'}
    instance.paths['logs'].mkdir()
    (instance.paths['scratch']/'grok-home').mkdir(parents=True)
    instance.model = batch.SONNET
    instance.proxy_name = 'test-proxy'
    instance.network = 'test-network'
    def popen(argv, **kwargs):
        env = kwargs['env']
        assert env['STUDY_SONNET_MIN_SPACING_S'] == '20'
        assert env['STUDY_ROUTE_DIAGNOSTICS'] == str(tmp_path/'diagnostics.jsonl')
        Path(env['STUDY_ROUTE_SOCKET']).touch()
        return SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(study_container.subprocess, 'Popen', popen)
    instance._docker = lambda args: SimpleNamespace(stdout='test-container')
    instance._start_model_route()


def test_completed_restart_does_not_admit_again(tmp_path, monkeypatch):
    m = manifest(batch.SONNET)
    m['jobs'] = m['jobs'][:1]
    def execute(job, manifest, row):
        artifact = batch.study.episode_dir(Path(row['attempt_root']), job['job_id'])
        artifacts(job, artifact)
        return {'status':'ok', 'artifact':str(artifact), 'returncode':0}
    monkeypatch.setattr(batch, 'execute', execute)
    first = batch.run_model(m, tmp_path)
    assert first['state'] == 'completed'
    monkeypatch.setattr(batch, 'execute', lambda *a: pytest.fail('duplicate launch'))
    second = batch.run_model(m, tmp_path)
    assert len(second['attempts']) == 1


def test_mutated_failed_artifacts_block_replacement(tmp_path, monkeypatch):
    m = manifest(batch.SONNET)
    ledger = {'attempts':[], 'state':'paused_quota'}
    failed = batch.admit(m, ledger, tmp_path, m['jobs'][0])
    payload = Path(failed['attempt_root'])/'failure.json'
    payload.write_text('{}')
    failed.update(status='incomplete', quota_failure=True, retry_not_before=0)
    batch.amend(m, ledger, tmp_path)
    monkeypatch.setattr(batch.time, 'time', lambda: ledger['amendment']['not_before'] + 1)
    payload.write_text('{"changed":true}')
    with pytest.raises(RuntimeError, match='artifacts changed'):
        batch.admit(m, ledger, tmp_path, m['jobs'][0], failed)


def test_seeded_phase_order_is_reproducible_and_not_lexicographic():
    jobs = batch.select_jobs()
    assert jobs == batch.select_jobs()
    assert all(j['arm'] == 'control' for j in jobs[:4])
    canonical = sorted(jobs, key=lambda j: j['job_id'])
    assert jobs != canonical
    for model in batch.CAPS:
        attacks = [j['job_id'] for j in jobs if j['model'] == model and j['arm'] != 'control']
        assert attacks != sorted(attacks)


@pytest.mark.parametrize('tail', ['{', '{"event":', '{"event":"res', '{"status":tru', '{"wait":1.', '{"wait":1e-', r'{"text":"\u00'])
def test_active_trailing_json_only(tmp_path, tail):
    path = tmp_path/'events.jsonl'
    path.write_text('{"status":200}\n' + tail)
    assert batch.read_events(path, active=True) == [{'status':200}]
    with pytest.raises(json.JSONDecodeError):
        batch.read_events(path)
    wake = tmp_path/'wake.json'
    wake.write_text(tail)
    assert batch.read_active_json(wake) is None
    wake.write_text('{"returncode":0}\n')
    assert batch.read_active_json(wake) == {'returncode':0}


@pytest.mark.parametrize('text', ['{"bad":oops}', '{"bad":}\n', '{"bad":\n{"status":200}\n'])
def test_active_malformed_committed_json_fails(tmp_path, text):
    path = tmp_path/'events.jsonl'
    path.write_text(text)
    with pytest.raises(json.JSONDecodeError):
        batch.read_events(path, active=True)


def test_amendment_uses_model_lock_while_global_controller_held(tmp_path, monkeypatch):
    m = manifest(batch.SONNET)
    directory = tmp_path/batch.SONNET
    directory.mkdir()
    ledger = {'attempts':[], 'state':'paused_quota'}
    failed = batch.admit(m, ledger, directory, m['jobs'][0])
    (Path(failed['attempt_root'])/'failure.json').write_text('{}')
    failed.update(status='incomplete', quota_failure=True, retry_not_before=0)
    batch.save(directory/'attempts.json', ledger)
    monkeypatch.setattr(batch, 'verify', lambda *a, **k: {batch.SONNET:m})
    monkeypatch.setattr(sys, 'argv', ['next', '--run-dir', str(tmp_path), '--amend-sonnet-quota'])
    with batch.exclusive(tmp_path/'runner.lock'):
        with batch.exclusive(directory/'model.lock'):
            with pytest.raises(BlockingIOError):
                batch.main()
        assert batch.main() == 0
    assert batch.read_json(directory/'attempts.json')['state'] == 'replacement_authorized'


def test_active_partial_writer_finishes_without_false_pause(tmp_path, monkeypatch):
    import threading
    m = manifest(batch.SONNET)
    m['jobs'] = m['jobs'][:1]
    written = threading.Event()
    checked = threading.Event()
    original = batch.read_events
    def read(path, **kwargs):
        value = original(path, **kwargs)
        if kwargs.get('active') and written.is_set():
            checked.set()
        return value
    monkeypatch.setattr(batch, 'read_events', read)
    def execute(job, manifest, row):
        root = Path(row['attempt_root'])
        diagnostic = root/'route-diagnostics.jsonl'
        diagnostic.write_text('{"status":200}\n{"event":')
        wake = batch.study.episode_dir(root, job['job_id'])/'wakes/01.json'
        wake.parent.mkdir(parents=True)
        wake.write_text('{"returncode":')
        written.set()
        assert checked.wait(5)
        diagnostic.write_text('{"status":200}\n')
        wake.write_text('{"turn":1,"returncode":0}\n')
        return {'status':'ok'}
    monkeypatch.setattr(batch, 'execute', execute)
    assert batch.run_model(m, tmp_path)['state'] == 'completed'


def test_run_model_rejects_unfinished_write_at_completion(tmp_path, monkeypatch):
    m = manifest(batch.SONNET)
    m['jobs'] = m['jobs'][:1]
    def execute(job, manifest, row):
        (Path(row['attempt_root'])/'route-diagnostics.jsonl').write_text('{"event":')
        return {'status':'ok'}
    monkeypatch.setattr(batch, 'execute', execute)
    result = batch.run_model(m, tmp_path)
    assert result['state'] != 'completed'
    assert result['attempts'][0]['status'] == 'incomplete'


def test_completed_trailing_diagnostic_fails_strictly(tmp_path, monkeypatch):
    m = manifest(batch.SONNET)
    row = batch.admit(m, {'attempts':[]}, tmp_path, m['jobs'][0])
    root = Path(row['attempt_root'])
    artifacts(m['jobs'][0], batch.study.episode_dir(root, m['jobs'][0]['job_id']))
    (root/'route-diagnostics.jsonl').write_text('{"status":200}\n{"event":')
    monkeypatch.setattr(batch.study, 'launch_cli_episode', lambda *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(batch.study, 'collect_attempt_usage', lambda p: {})
    result = batch.execute(m['jobs'][0], m, row)
    assert result['status'] == 'incomplete'
    assert result['error_type'] == 'DiagnosticParseError'


def test_stream_error_overrides_successful_artifacts(tmp_path, monkeypatch):
    m = manifest(batch.SONNET)
    row = batch.admit(m, {'attempts':[]}, tmp_path, m['jobs'][0])
    root = Path(row['attempt_root'])
    artifacts(m['jobs'][0], batch.study.episode_dir(root, m['jobs'][0]['job_id']))
    (root/'route-diagnostics.jsonl').write_text(
        '{"event":"response","status":200,"at":99,"request_id":"r","retry_after_s":180}\n'
        '{"event":"stream_error","status":429,"at":100,"request_id":"r"}\n')
    monkeypatch.setattr(batch.study, 'launch_cli_episode', lambda *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(batch.study, 'collect_attempt_usage', lambda p: {})
    result = batch.execute(m['jobs'][0], m, row)
    assert result['status'] == 'incomplete' and result['quota_failure']
    assert result['retry_not_before'] == 279
