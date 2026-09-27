
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import importlib.util
import concurrent.futures
import json
import time
import pytest
from pathlib import Path

P=Path(__file__).resolve().parents[1]/'scripts/study/sonnet_pacing.py'
spec=importlib.util.spec_from_file_location('sonnet_pacing',P)
pacing=importlib.util.module_from_spec(spec)
spec.loader.exec_module(pacing)


def test_spacing_and_persistent_state(tmp_path,monkeypatch):
    clock=[100.0]
    monkeypatch.setattr(pacing.time,'time',lambda:clock[0])
    monkeypatch.setattr(pacing.time,'sleep',lambda seconds:clock.__setitem__(0,clock[0]+seconds))
    p=tmp_path/'state.json'
    assert pacing.reserve_start(p)==0
    assert pacing.reserve_start(p)==65
    clock[0]+=70
    assert pacing.reserve_start(p)==0
    assert pacing.reserve_start(p,20)==20


@pytest.mark.parametrize('value', [0, -1, 'nan', 'inf', '-inf', 'bad'])
def test_invalid_spacing(tmp_path, value):
    with pytest.raises(ValueError):
        pacing.reserve_start(tmp_path/'state.json', value)
    assert not (tmp_path/'state.json').exists()


def test_concurrent_admission_serializes(tmp_path):
    path = tmp_path/'state.json'
    def reserve(_):
        pacing.reserve_start(path, 0.03)
        return time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        starts = sorted(pool.map(reserve, range(3)))
    assert all(b-a >= 0.025 for a,b in zip(starts, starts[1:]))
    assert json.loads(path.read_text())['last_start'] > 0
