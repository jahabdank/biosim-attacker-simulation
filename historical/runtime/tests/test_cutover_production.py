"""Production path via subprocess fakes. Root guard first; no facts-injection verify."""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "docker-migration"))

from cutover import Cfg, Engine, CutoverError, load_pg_env  # noqa: E402

DISP = ROOT / "tests" / "fakes" / "dispatcher.py"


def _setup(tmp: Path, *, password: bool = True, hold: bool = True):
    bindir = tmp / "bin"
    bindir.mkdir()
    names = ("snap-docker", "apt-docker", "snap", "apt-get", "systemctl")
    for n in names:
        dest = bindir / n
        dest.write_text("#!/usr/bin/env python3\n" + DISP.read_text().split("#!/usr/bin/env python3\n", 1)[-1])
        dest.chmod(0o755)
        # dispatcher is the file; easier: symlink to dispatcher
        dest.unlink()
        dest.symlink_to(DISP)
        dest.chmod(0o755)
    DISP.chmod(0o755)
    state = tmp / "state"
    state.mkdir()
    (state / "PARENT-CUTOVER-OK").write_text("reviewed\n")
    env = tmp / "pg.env"
    if password:
        env.write_text("POSTGRES_PASSWORD=secret\nPOSTGRES_USER=provider_proxy\nPOSTGRES_DB=provider_proxy\n")
    else:
        env.write_text("POSTGRES_USER=provider_proxy\nPOSTGRES_DB=provider_proxy\n")
    holdp = tmp / "MAINTENANCE-HOLD-ATTESTED"
    if hold:
        holdp.write_text("manual drain attested\n")
    fake_state = tmp / "fake.json"
    fake_state.write_text("{}")
    os.environ["FAKE_STATE"] = str(fake_state)
    cfg = Cfg(
        state_dir=state,
        snap_docker=str(bindir / "snap-docker"),
        apt_docker=str(bindir / "apt-docker"),
        snap=str(bindir / "snap"),
        apt_get=str(bindir / "apt-get"),
        systemctl=str(bindir / "systemctl"),
        env_file=env,
        hold_attest=holdp if hold else tmp / "no-hold",
        min_free=1,
        pg_ready_deadline_s=2.0,
        quiesce_gap_s=0.0,
    )
    return cfg, fake_state


def _calls(fake_state: Path) -> list[list[str]]:
    return json.loads(fake_state.read_text()).get("calls") or []


def _first_idx(calls, pred) -> int:
    for i, c in enumerate(calls):
        if pred(c):
            return i
    return -1


def test_root_guard_before_any_docker(tmp_path: Path):
    cfg, fake = _setup(tmp_path)
    eng = Engine(cfg, euid=1000)
    with pytest.raises(CutoverError, match="root required"):
        eng.run()
    assert _calls(fake) == [] or all("dumpall" not in " ".join(c) for c in _calls(fake))
    # guards must not have dumped
    assert not any("pg_dumpall" in " ".join(c) for c in _calls(fake))


def test_missing_password_before_stop(tmp_path: Path):
    cfg, fake = _setup(tmp_path, password=False)
    eng = Engine(cfg, euid=0)
    with pytest.raises(CutoverError, match="POSTGRES_PASSWORD"):
        eng.run()
    assert not any(c[:2] == [cfg.snap, "disable"] for c in _calls(fake))


def test_download_failure_leaves_snap_up(tmp_path: Path):
    cfg, fake = _setup(tmp_path)
    fake.write_text(json.dumps({"fail_download": True}))
    eng = Engine(cfg, euid=0)
    with pytest.raises(CutoverError):
        eng.run()
    calls = _calls(fake)
    assert any("--download-only" in c for c in calls)
    assert not any(c[:2] == [cfg.snap, "disable"] for c in calls)
    assert not any(c[:2] == [cfg.snap, "stop"] for c in calls)


def test_install_failure_restores_snap(tmp_path: Path):
    cfg, fake = _setup(tmp_path)
    fake.write_text(json.dumps({"fail_install": True}))
    eng = Engine(cfg, euid=0)
    with pytest.raises(CutoverError):
        eng.run()
    calls = _calls(fake)
    assert any(c[:2] == [cfg.snap, "disable"] for c in calls)
    assert any(c[:2] == [cfg.snap, "enable"] for c in calls)
    assert any(c[:2] == [cfg.snap, "start"] for c in calls)
    assert any(c[:3] == [cfg.snap_docker, "start", "provider_proxy-postgres"] for c in calls)


def test_nnp_failure_restores_snap(tmp_path: Path):
    cfg, fake = _setup(tmp_path)
    fake.write_text(json.dumps({"fail_nnp": True}))
    eng = Engine(cfg, euid=0)
    with pytest.raises(CutoverError, match="nnp"):
        eng.run()
    calls = _calls(fake)
    assert any(c[:2] == [cfg.snap, "start"] for c in calls)


def test_happy_path_queries_new_db_and_download_before_stop(tmp_path: Path):
    cfg, fake = _setup(tmp_path)
    eng = Engine(cfg, euid=0)
    out = eng.run()
    assert out["ok"] is True
    calls = _calls(fake)
    dl = _first_idx(calls, lambda c: "--download-only" in c)
    stop = _first_idx(calls, lambda c: c[:2] == [cfg.snap, "disable"])
    dump = _first_idx(calls, lambda c: "pg_dumpall" in " ".join(c))
    assert dl != -1 and stop != -1 and dump != -1
    assert dump < stop and dl < stop
    # NEW db queried via apt-docker exec ... -Atc
    new_q = [
        c
        for c in calls
        if c[0] == cfg.apt_docker and "exec" in c and "-Atc" in c
    ]
    assert new_q, "production must query NEW postgres, not reuse attest dict"
    assert any("--env-file" in c for c in calls if c[0] == cfg.apt_docker and "run" in c)
    dumpf = cfg.state_dir / "backups" / "pg_dumpall.sql"
    assert dumpf.is_file()
    assert (dumpf.stat().st_mode & 0o777) == 0o600


def test_idle_sessions_without_attest_refuse_before_stop(tmp_path: Path):
    cfg, fake = _setup(tmp_path, hold=False)
    fake.write_text(json.dumps({"activity": "99 | provider_proxy | idle | Client | SELECT 1\n"}))
    eng = Engine(cfg, euid=0)
    with pytest.raises(CutoverError, match="MAINTENANCE-HOLD-ATTESTED"):
        eng.run()
    assert not any(c[:2] == [cfg.snap, "disable"] for c in _calls(fake))


def test_unknown_exception_still_rolls_back(tmp_path: Path):
    cfg, fake = _setup(tmp_path)
    eng = Engine(cfg, euid=0)

    def boom(*_a, **_k):
        raise RuntimeError("unexpected")

    eng._invariants = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="unexpected"):
        eng.run()
    calls = _calls(fake)
    assert any(c[:2] == [cfg.snap, "start"] or c[:2] == [cfg.systemctl, "stop"] for c in calls)


def test_load_pg_env_requires_password(tmp_path: Path):
    p = tmp_path / "e"
    p.write_text("POSTGRES_USER=provider_proxy\n")
    with pytest.raises(CutoverError, match="PASSWORD"):
        load_pg_env(p)
