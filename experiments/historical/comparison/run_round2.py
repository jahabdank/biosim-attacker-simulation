"""Bounded replication using the verified original runtime, no automatic retries."""

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import concurrent.futures
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time

SOURCE=Path(_archive_root())
BASE=Path(str(_archive_path('path_049')))
sys.path[:0]=[str(SOURCE/'src'),str(SOURCE/'scripts')]
from biosim_operator import study
from run_terra_comparison_smoke import save


def execute(root, job):
    root.mkdir()
    state=dict(state='running',job=job,started=time.time(),controller_pid=os.getpid())
    save(root/'status.json',state)
    env=dict(os.environ)
    if job['model']=='grok-4.6':
        env.pop('STUDY_ROUTE_DIAGNOSTICS',None)
        env.pop('STUDY_ROUTE_PACING',None)
    else:
        env.update(STUDY_ROUTE_MODEL=job['model'],STUDY_ROUTE_PACING='1',
                   STUDY_ROUTE_MIN_SPACING_S=str(job['minimum_spacing_s']),
                   STUDY_ROUTE_TIMEOUT_S='1800',STUDY_ROUTE_DIAGNOSTICS=str(root/'route-diagnostics.jsonl'))
    try:
        p=study.launch_cli_episode(job,run_dir=root,env=env,extra_argv=['--timeout','1800','--max-tool-turns','16'])
        ep=study.episode_dir(root,job['job_id']);o=json.load((ep/'outcome.json').open()) if (ep/'outcome.json').exists() else {}
        state.update(state='completed' if p.returncode==0 and o and not o.get('incomplete') else 'failed',
                     returncode=p.returncode,artifact=str(ep),n_dead=o.get('n_dead'))
    except Exception as e:state.update(state='failed',error=repr(e))
    state['ended']=time.time();save(root/'status.json',state)
    return state


def lane(run,model,jobs):
    folder=run/model;folder.mkdir()
    state=dict(state='running',model=model,completed=0,controller_pid=os.getpid())
    save(folder/'status.json',state)
    locks=[]
    try:
        for name in [model]+(['provider_a-episode'] if model.startswith('claude-') else []):
            f=Path('/run/lock/biosim-'+name+'.lock').open('a+');locks.append(f)
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for j in jobs:
            result=execute(folder/j['job_id'].replace(':','__'),j)
            if result['state']=='failed':
                state.update(state='failed',failed=j['job_id']);break
            state['completed']+=1;save(folder/'status.json',state)
            time.sleep(15)
        else:state['state']='completed'
    except Exception as e:state.update(state='failed',error=repr(e))
    finally:
        save(folder/'status.json',state)
        for f in locks:f.close()
    return state


def main():
    baseline=json.load(BASE.open())
    for name,digest in baseline['source_hashes'].items():
        p=SOURCE/name
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Original runtime fingerprint changed: '+name)
    lock=Path('/run/lock/biosim-dual-prompt-round2.lock').open('a+')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    run=Path(sys.argv[1]);run.mkdir(parents=True,exist_ok=False)
    jobs=copy.deepcopy(baseline['jobs'])
    jobs['claude-sonnet-5']=copy.deepcopy(jobs['gpt-5.6-terra'])
    for i,(model,items) in enumerate(jobs.items()):
        for j in items:
            j.update(model=model,repeat=2 if model!='claude-sonnet-5' else 1,
                     study_id=run.name,minimum_spacing_s=120 if model=='claude-sonnet-5' else 15)
            j['job_id']=f"dual-prompt-round2:{model}:{j['experiment']}:attack:t1:{j['story']}:r{j['repeat']:02d}"
            if model=='claude-sonnet-5':j.update(context_window=1000000,route='configured-provider')
        random.Random(20260915+i).shuffle(items)
    assert sum(map(len,jobs.values()))==30
    save(run/'manifest.json',dict(jobs=jobs,baseline_manifest_sha256=hashlib.sha256(BASE.read_bytes()).hexdigest(),
         source_hashes=baseline['source_hashes'],attempt_cap=30,retries=0,per_model_concurrency=1,
         pacing={'provider_a_seconds':120,'provider_a_seconds':15,'native':'serial native CLI; no per-request throttle exposed,15s between episodes'},
         comparison_notes='Original prompts/scripts/runtime byte-verified. Sonnet new coverage. Original native subscription credential-copy exception retained; not credential-free.'))
    save(run/'status.json',dict(state='running',controller_pid=os.getpid(),started=time.time()))
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        results=[f.result() for f in [pool.submit(lane,run,m,items) for m,items in jobs.items()]]
    save(run/'status.json',dict(state='completed' if all(x['state']=='completed' for x in results) else 'partial_failure',ended=time.time(),lanes=results))


if __name__=='__main__':main()
