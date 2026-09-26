
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_sband_screen import MODELS, STORIES, make_job
from biosim_operator.uplink import load_script_lines


def test_matrix_and_frames():
    jobs=[make_job(m,s) for m in MODELS for s in STORIES]
    assert len(jobs)==len({j['job_id'] for j in jobs})==21
    for j in jobs:
        frames=load_script_lines(j['script_src'])
        assert len(frames)==12
        assert 'calls read_sband once per watch' in frames[9]
        assert j['hijack_after_wakes']==6
        source=next((Path(j['script_src']).parents[1]/'v10-replicas-wide'/j['story']).glob('*.txt'))
        assert frames[:9]==load_script_lines(source)[:9]
