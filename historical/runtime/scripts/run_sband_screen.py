"""Bounded seven-model, three-story attack-first screen. No retries or controls."""

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import concurrent.futures
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from biosim_operator import study
from run_terra_comparison_smoke import save
MODELS=('grok-4.6-route-b','claude-sonnet-5','claude-opus-5','gpt-5.6-luna','gpt-5.6-terra','gpt-5.6-sol','claude-haiku-4-5')
STORIES=('rehearsal-cabin','safing-closeout','spare-desk')


def make_job(model,story):
    script=ROOT/'data/hijack_scripts/v10-sband-adapted'/f'{story}.txt'
    return dict(job_id=f'sband-system-only:{model}:attack:t1:{story}:r01',study_id='sband-system-only-20260911',
                model=model,route='configured-provider',context_window=140000 if model=='claude-haiku-4-5' else 1050000,
                route_a_fallback=False,story=story,trust='t1',repeat=1,arm='attack',envelope='peer',probe='hijack',
                script_src=str(script),script_bank='v10-sband-adapted',script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
                identity_dir=str(ROOT/'packs/sband-system-only-t1-peer'),interrupt_p=1.0,hijack_after_wakes=6,
                sband_separator='--- PEER MESSAGE ---',launchable=True,per_episode_jvm=True,technical=False)


def lane(run,model,jobs):
    folder=run/model;folder.mkdir()
    lock=Path('/run/lock/biosim-'+model+'.lock').open('a+')
    state=dict(state='running',model=model,controller_pid=os.getpid(),completed=0)
    save(folder/'status.json',state)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for job in jobs:
            attempt=folder/job['story'];attempt.mkdir()
            receipt=dict(state='running',job=job,started=time.time(),controller_pid=os.getpid())
            save(attempt/'status.json',receipt)
            env=dict(os.environ,STUDY_ROUTE_PACING='1',STUDY_ROUTE_MIN_SPACING_S='90' if model.startswith('claude-') else '15',
                     STUDY_ROUTE_MODEL=model,STUDY_ROUTE_TIMEOUT_S='1800',STUDY_ROUTE_DIAGNOSTICS=str(attempt/'route-diagnostics.jsonl'))
            try:
                proc=study.launch_cli_episode(job,run_dir=attempt,env=env,extra_argv=['--timeout','1800','--max-tool-turns','16'])
                ep=study.episode_dir(attempt,job['job_id']);p=ep/'outcome.json'
                d=json.load(p.open()) if p.exists() else {}
                receipt.update(state='completed' if proc.returncode==0 and d and not d.get('incomplete') else 'failed',returncode=proc.returncode,artifact=str(ep),n_dead=d.get('n_dead'))
            except Exception as exc:
                receipt.update(state='failed',error=repr(exc))
            receipt['ended']=time.time();save(attempt/'status.json',receipt)
            if receipt['state']=='failed':
                state.update(state='failed',failed_story=job['story']);break
            state['completed']+=1;save(folder/'status.json',state)
        else:state['state']='completed'
    except Exception as exc:state.update(state='failed',error=repr(exc))
    finally:save(folder/'status.json',state)
    return state


def main():
    run=Path(sys.argv[1]);run.mkdir(parents=True,exist_ok=False)
    lock=Path('/run/lock/biosim-terra-comparison.lock').open('a+')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    jobs={}
    for i,m in enumerate(MODELS):
        order=list(STORIES);random.Random(20260911+i).shuffle(order);jobs[m]=[make_job(m,s) for s in order]
    hashes={}
    for directory in ('src','scripts','configs','docker/study','packs/sband-system-only-t1-peer','data/hijack_scripts/v10-sband-adapted'):
        for p in (ROOT/directory).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:hashes[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
    save(run/'manifest.json',dict(jobs=jobs,source_hashes=hashes,max_attempts=21,retries=0,controls=0,max_per_model=1,max_total=5,provider_a_concurrency=1,provider_a_spacing_seconds=90))
    save(run/'status.json',dict(state='running',controller_pid=os.getpid(),started=time.time()))
    def provider_a_serial():
        provider_a_lock=Path('/run/lock/biosim-provider_a-episode.lock').open('a+')
        try:
            fcntl.flock(provider_a_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return [dict(state='failed',model=m,error='PROVIDER_A episode lock occupied') for m in MODELS if m.startswith('claude-')]
        return [lane(run,m,jobs[m]) for m in MODELS if m.startswith('claude-')]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures=[pool.submit(lane,run,m,jobs[m]) for m in MODELS if not m.startswith('claude-')]
        provider_a=pool.submit(provider_a_serial)
        results=[f.result() for f in futures]+provider_a.result()
    save(run/'status.json',dict(state='completed' if all(r['state']=='completed' for r in results) else 'partial_failure',controller_pid=os.getpid(),ended=time.time(),lanes=results))
    return 0 if all(r['state']=='completed' for r in results) else 2


if __name__=='__main__':raise SystemExit(main())
