
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

from pathlib import Path

from biosim_operator.study import MATHUTILS_EVA, collect_fingerprints


def test_mathutils_rng_is_jvm_static_not_per_sim():
    assert MATHUTILS_EVA.is_file()
    text = MATHUTILS_EVA.read_text()
    assert "private static final Random myRandom" in text
    prints = collect_fingerprints()
    assert prints["plant_rng"]["jvm_static_random"] is True
    assert prints["plant_rng"]["paired_trajectories"] is False
    assert "per-episode JVM" in prints["isolation"]
