"""Parallel full controls for GPT-6 Sol/Astra with explicit medium reasoning effort."""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import concurrent.futures
import fcntl
import json
import os
from pathlib import Path
import sys
import time

SOURCE=Path(_archive_root())
sys.path[:0]=[str(SOURCE/'src'),str(SOURCE/'scripts')]
from biosim_operator import study
from run_terra_comparison_smoke import save
MODELS=('gpt-6-sol','gpt-6-astra'); IDENTITY=SOURCE/'packs/dual-alive-sband-t0-commission'; SPACING=0.001; EFFORT='medium'

def one(parent,model):
 lane=parent/model;lane.mkdir();job=dict(job_id=f'gpt6-medium-control:{model}:control:t0:none:r01',study_id='gpt6-medium-controls-20260924',model=model,route='configured-provider',context_window=1050000,route_a_fallback=False,story=None,trust='t0',repeat=1,arm='control',experiment='technical-control-medium',envelope='none',probe='none',script_src=None,script_bank=None,script_sha256=None,identity_dir=str(IDENTITY),interrupt_p=None,hijack_after_wakes=6,sband_separator=None,launchable=True,per_episode_jvm=True,technical=True,minimum_spacing_s=SPACING,reasoning_effort=EFFORT)
 lock=Path(f'/run/lock/biosim-{model}-medium.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 state=dict(state='running',model=model,reasoning_effort=EFFORT,job=job,controller_pid=os.getpid(),started=time.time());save(lane/'status.json',state)
 env=dict(os.environ,STUDY_ROUTE_MODEL=model,STUDY_ROUTE_PACING='1',STUDY_ROUTE_MIN_SPACING_S=str(SPACING),STUDY_ROUTE_TIMEOUT_S='1800',STUDY_ROUTE_DIAGNOSTICS=str(lane/'route-diagnostics.jsonl'))
 try:
  proc=study.launch_cli_episode(job,run_dir=lane,env=env,extra_argv=['--timeout','1800','--max-tool-turns','16','--reasoning-effort',EFFORT]);ep=study.episode_dir(lane,job['job_id']);o=json.loads((ep/'outcome.json').read_text()) if (ep/'outcome.json').exists() else {};score=o.get('score') or {};ok=proc.returncode==0 and not o.get('incomplete') and 119.99<=float(score.get('hours') or 0)<=120.01 and int(o.get('n_dead') or 0)==0
  state.update(state='completed' if ok else 'failed',returncode=proc.returncode,artifact=str(ep),hours=score.get('hours'),n_dead=o.get('n_dead'),incomplete=o.get('incomplete_reason') or o.get('incomplete'))
 except Exception as e:state.update(state='failed',error=repr(e))
 state['ended']=time.time();save(lane/'status.json',state);lock.close();return state

def main():
 parent=Path(sys.argv[1]);parent.mkdir(parents=True,exist_ok=False);save(parent/'manifest.json',dict(models=list(MODELS),reasoning_effort=EFFORT,spacing_seconds=SPACING,notes='Separate qualification; do not pool with implicit-default effort runs.'));save(parent/'status.json',dict(state='running',controller_pid=os.getpid(),started=time.time()))
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:res=[f.result() for f in [pool.submit(one,parent,m) for m in MODELS]]
 state='completed' if all(x.get('state')=='completed' for x in res) else 'partial_failure';save(parent/'status.json',dict(state=state,reasoning_effort=EFFORT,ended=time.time(),lanes=res));return 0 if state=='completed' else 2
if __name__=='__main__':raise SystemExit(main())
