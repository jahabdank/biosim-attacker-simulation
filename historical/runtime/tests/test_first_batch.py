
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import importlib.util
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("first_batch", ROOT / "scripts/study/run_first_batch.py")
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


def test_batch_covers_full_design():
    jobs = batch.select_jobs()
    assert len(jobs) == 72
    assert len({j["job_id"] for j in jobs}) == 72
    assert Counter(j["model"] for j in jobs) == {"grok-4.6":28,"gpt-5.6-luna":22,"claude-sonnet-5":22}
    for model in batch.CAPS:
        attacks = [j for j in jobs if j["model"] == model and j["arm"] == "attack"]
        assert len(attacks) == 18
        assert Counter(j["trust"] for j in attacks) == {"t0":6,"t1":6,"t2":6}


def test_station_preparation_accepts_existing_destination(tmp_path, monkeypatch):
    from biosim_operator import study_container as container
    monkeypatch.setattr(container, "STUDY_EPISODES", tmp_path)
    station = tmp_path / "episode" / "station"
    station.mkdir(parents=True)
    for name in ("SOUL.md", "STATION.md", "AGENTS.md"):
        (station / name).write_text("station document")
    container.prepare_episode_dirs("episode", station)
    assert (station / "SOUL.md").read_text() == "station document"


def test_cli_does_not_shadow_atexit():
    from biosim_operator.cli_episode import main
    assert "atexit" not in main.__code__.co_varnames


def test_caps_and_order_are_fixed():
    assert batch.CAPS == {"grok-4.6":4,"gpt-5.6-luna":3,"claude-sonnet-5":1}
    assert batch.select_jobs() == batch.select_jobs()
    assert all(j["arm"]=="control" for j in batch.select_jobs()[:9])
