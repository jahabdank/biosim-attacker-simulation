#!/usr/bin/env python3
"""Single authorized Terra qualification; attacks remain separately gated."""

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from biosim_operator import study


def save(path, data):
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def main():
    run = Path(sys.argv[1])
    run.mkdir(parents=True, exist_ok=True)
    lock = Path('/run/lock/biosim-terra-comparison.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    ledger = run / 'status.json'
    if ledger.exists():
        raise RuntimeError('Attempt already reserved; no automatic replacement')
    job = dict(job_id='terra-consequence-smoke:control:t1:none:r01',
               study_id='terra-consequence-smoke-20260910', model='gpt-5.6-terra',
               route='existing-provider_a-route', context_window=1050000,
               route_a_fallback=False, story=None, trust='t1', repeat=1,
               arm='control', envelope='none', probe='none', script_src=None,
               script_bank=None, script_sha256=None,
               identity_dir=str(ROOT / 'packs/advanced-t1-peer'),
               interrupt_p=None, hijack_after_wakes=6, sband_separator=None,
               launchable=True, per_episode_jvm=True, technical=True)
    hashes = {}
    for directory in ('src', 'scripts/study', 'packs/advanced-t1-peer', 'configs', 'docker/study'):
        for p in (ROOT / directory).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:
                hashes[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    save(run / 'manifest.json', {'job': job, 'source': hashes, 'attempt_cap': 1,
                               'attacks_authorized_by_this_controller': False})
    state = dict(state='running', pid=os.getpid(), started=time.time(), job=job)
    save(ledger, state)
    env = dict(os.environ, STUDY_ROUTE_MODEL='gpt-5.6-terra', STUDY_ROUTE_PACING='1',
               STUDY_ROUTE_MIN_SPACING_S='15', STUDY_ROUTE_DIAGNOSTICS=str(run/'route-diagnostics.jsonl'))
    try:
        result = study.launch_cli_episode(job, run_dir=run, env=env,
                                         extra_argv=['--timeout', '1800', '--max-tool-turns', '16'])
        artifact = study.episode_dir(run, job['job_id'])
        outcome = json.loads((artifact/'outcome.json').read_text())
        score = outcome.get('score', {})
        state.update(state='completed' if result.returncode == 0 and not outcome.get('incomplete') else 'failed',
                     returncode=result.returncode, artifact=str(artifact),
                     n_dead=outcome.get('n_dead'), hours=score.get('hours'))
        # Full qualification additionally requires independent tool/identity/roster inspection.
    except Exception as exc:
        state.update(state='failed', error=repr(exc))
    finally:
        state['ended'] = time.time()
        save(ledger, state)
    return 0 if state['state'] == 'completed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
