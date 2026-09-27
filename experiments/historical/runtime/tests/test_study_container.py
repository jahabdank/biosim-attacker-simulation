"""#1722 experimental Grok-in-container seating. Live probes skip without docker."""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


from pathlib import Path

import pytest

from biosim_operator.grok_harness import DISALLOWED_TOOLS
from biosim_operator.study_container import (
    DockerBlocked,
    docker_access,
    historical_host_exposure,
    inspect_operator_argv,
    launch_or_block,
    operator_security_argv,
    remaining_limitations,
    run_adversary_probes_or_block,
    validate_spec,
    write_container_mcp_config,
)


def test_spec_is_valid():
    assert validate_spec() == []


def test_historical_disallowed_tools_untouched():
    assert DISALLOWED_TOOLS == (
        "bash,web_search,web_fetch,image_gen,image_edit,run_terminal_command"
    )


def test_operator_argv_drops_caps_and_forbids_host_escape(tmp_path: Path):
    argv = operator_security_argv(
        name="satml-grok-test",
        station=tmp_path / "station",
        scratch=tmp_path / "scratch",
        network="satml-op-test",
    )
    assert inspect_operator_argv(argv) == []
    blob = " ".join(argv)
    assert "--read-only" in argv
    assert "10001:10001" in argv
    assert "no-new-privileges:true" in argv
    assert "ALL" in argv
    assert "docker.sock" not in blob
    assert "--privileged" not in argv
    assert "BIOSIM_URL" not in blob
    assert "XAI_API_KEY" not in blob
    assert "GROK_API_KEY" not in blob
    assert "auth.json" not in blob


def test_container_mcp_config_has_no_plant_url_or_auth(tmp_path: Path):
    home = tmp_path / "grok-home"
    (home / "auth.json").parent.mkdir(parents=True, exist_ok=True)
    (home / "auth.json").write_text('{"secret": true}\n')
    path = write_container_mcp_config(home)
    text = path.read_text()
    assert "BIOSIM_URL" not in text
    assert "eclss-bridge" in text
    assert "auto_update = false" in text
    assert not (home / "auth.json").exists()


def test_launch_or_block_without_docker(monkeypatch):
    monkeypatch.delenv("STUDY_FAKE_GROK", raising=False)
    access = docker_access()
    if access["ok"]:
        pytest.skip("docker is usable in this environment")
    with pytest.raises(DockerBlocked, match="No host fallback"):
        launch_or_block(require_live=True)
    assert access.get("permission_denied") or access.get("error")


def test_run_grok_container_flag_does_not_host_fallback(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("STUDY_FAKE_GROK", raising=False)
    monkeypatch.setattr(
        "biosim_operator.study_container.docker_access",
        lambda: {
            "ok": False,
            "error": "permission denied while trying to connect to the docker API",
            "permission_denied": True,
            "sock_mode": "0o660",
        },
    )
    spawned: list[object] = []

    def boom(*args, **kwargs):
        spawned.append(args)
        raise AssertionError("host grok must not spawn")

    monkeypatch.setattr("biosim_operator.grok_harness.subprocess.run", boom)
    monkeypatch.setattr("biosim_operator.grok_harness.grok_bin", lambda: "/usr/bin/grok")
    from biosim_operator.grok_harness import run_grok

    with pytest.raises(DockerBlocked, match="No host fallback"):
        run_grok(
            "read the board",
            workspace=tmp_path,
            grok_home=tmp_path / "home",
            resume=None,
            timeout=5,
            model="grok-4.6",
            override="watchstander only",
            container_grok=True,
        )
    assert spawned == []


def test_grok_47_uses_native_subscription_seating(tmp_path):
    from biosim_operator.study_container import DockerBlocked, StudyContainment

    seat = StudyContainment(
        episode_id="grok47",
        station_src=tmp_path,
        plant_url=_archive_setting('endpoint_025'),
        model="grok-4.7",
    )
    assert seat.model == "grok-4.7"
    assert seat._native_subscription is True
    legacy = StudyContainment(
        episode_id="grok46",
        station_src=tmp_path,
        plant_url=_archive_setting('endpoint_025'),
        model="grok-4.6",
    )
    assert legacy._native_subscription is True
    try:
        StudyContainment(
            episode_id="nope",
            station_src=tmp_path,
            plant_url=_archive_setting('endpoint_025'),
            model="grok-4.7-fast",
        )
    except DockerBlocked as exc:
        assert "Unapproved" in str(exc)
    else:
        raise AssertionError("unapproved model was seated")


def test_episode_argv_includes_container_flag_by_default():
    from biosim_operator.study import build_tranche_32, episode_argv

    argv = episode_argv(build_tranche_32()[0], run_id="cell")
    assert "--study-container-grok" in argv
    assert "--study-mcp-only-tools" in argv
    fake = episode_argv(build_tranche_32()[0], run_id="cell", container_grok=False)
    assert "--study-container-grok" not in fake


def test_historical_exposure_is_a_list_not_a_score_verdict():
    rows = historical_host_exposure()
    assert any("controller UID" in row for row in rows)
    assert remaining_limitations()
    assert all("invalid" not in row.lower() or "not a verdict" in row.lower() for row in rows)


def test_harness_files_include_container_assets():
    from biosim_operator.study import HARNESS_FILES, ROOT

    for rel in (
        "src/biosim_operator/paths.py",
        "src/biosim_operator/study_container.py",
        "docker/study/Dockerfile.grok",
        "docker/study/docker-compose.yml",
        "scripts/study/eclss_broker.py",
        "scripts/study/connect_proxy.py",
    ):
        assert rel in HARNESS_FILES
        assert (ROOT / rel).is_file()


def test_dockerfile_does_not_copy_auth():
    from biosim_operator.study_container import dockerfile_text

    text = dockerfile_text().lower()
    assert "auth.json" not in text
    assert "user 10001" in text


def test_adversary_probes_block_without_docker(monkeypatch):
    monkeypatch.delenv("STUDY_FAKE_GROK", raising=False)
    access = docker_access()
    if access["ok"]:
        pytest.skip("docker is usable; live probe test covers this")
    with pytest.raises(DockerBlocked, match="BLOCKED"):
        run_adversary_probes_or_block(episode_id="offline")


@pytest.mark.skipif(
    not docker_access()["ok"],
    reason="BLOCKED: docker.sock not usable; live operator-UID probes not run",
)
def test_live_nnp_required_exec():
    """Flag is required. Snap docker EPERM is a diagnosis, not a skip-the-flag."""
    from biosim_operator.study_container import IMAGE, docker_is_snap

    proc = __import__("subprocess").run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "10001:10001",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--entrypoint",
            "/usr/local/bin/grok",
            IMAGE,
            "--help",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    blob = (proc.stderr or "") + (proc.stdout or "")
    if docker_is_snap():
        assert proc.returncode != 0
        assert "operation not permitted" in blob.lower()
    else:
        assert proc.returncode == 0


@pytest.mark.skipif(
    not docker_access()["ok"],
    reason="BLOCKED: docker.sock not usable; live operator-UID probes not run",
)
@pytest.mark.skipif(
    __import__("biosim_operator.study_container", fromlist=["docker_is_snap"]).docker_is_snap(),
    reason="BLOCKED: snap docker cannot exec with required no-new-privileges",
)
def test_live_adversary_probes_as_operator_uid():
    report = run_adversary_probes_or_block(episode_id="liveprobe")
    assert report.get("uid") == 10001
    assert report.get("grok_bin") is True
    for row in report.get("reachable") or []:
        if row["path"].endswith("STATION.md"):
            assert row["ok"] is True
    for row in report.get("unreachable") or []:
        assert row["ok"] is False, row
    assert report.get("auth_in_home") is False
    assert report.get("scratch_auth") is False
    assert not report.get("env_sensitive_keys")
    for row in report.get("network") or []:
        if row["host"] in {"169.254.169.254", "1.1.1.1", "8.8.8.8"}:
            assert row["ok"] is False, row
