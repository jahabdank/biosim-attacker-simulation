
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

from pathlib import Path

from biosim_operator.cli_episode import CURSOR_DEFAULT_MODEL, cursor_cmd, cursor_home_for
from biosim_operator.diegesis import visible_eclss_command
from biosim_operator.containment import (
    COMPOSE_FILE,
    CONTAINER_WATCHES,
    EMPTY_PLUGINS,
    HOST_PLANT_URL,
    INSIDE_PLANT_URL,
    ROOT,
    enabled,
    host_workspace,
    inside_workspace,
    seat_name,
)


def test_ensure_stack_skips_recreate_when_plant_is_up(monkeypatch):
    from biosim_operator import containment

    monkeypatch.setattr(containment, "plant_is_up", lambda url=None, timeout=1.5: True)

    def boom(*_a, **_k):
        raise AssertionError("must not rebuild a live plant")

    monkeypatch.setattr(containment, "_compose", boom)
    containment.ensure_stack()


def test_docker_off_by_default(monkeypatch):
    monkeypatch.delenv("FARSIDE_DOCKER", raising=False)
    assert enabled() is False


def test_docker_enabled_from_env(monkeypatch):
    monkeypatch.setenv("FARSIDE_DOCKER", "1")
    assert enabled() is True
    monkeypatch.setenv("FARSIDE_DOCKER", "true")
    assert enabled() is True


def test_plant_urls_are_station_shaped():
    assert HOST_PLANT_URL == _archive_setting('endpoint_004')
    assert INSIDE_PLANT_URL == _archive_setting('endpoint_005')
    assert "biosim" not in INSIDE_PLANT_URL.lower()
    assert "attack" not in INSIDE_PLANT_URL.lower()


def test_inside_workspace_is_the_seating_not_a_sibling_id(tmp_path: Path):
    host = tmp_path / "W-ABCDEF12"
    assert inside_workspace(host) == CONTAINER_WATCHES
    assert seat_name("W-ABCDEF12") == "farside-seat-w-abcdef12"


def test_compose_services_are_plant_and_console():
    text = COMPOSE_FILE.read_text()
    assert "container_name: farside-plant" in text
    assert "farside-console:watch" in text
    assert "hostname: plant" in text
    assert 'profiles: ["manual"]' in text
    assert "\n  biosim:" not in text
    assert "\n  operator:" not in text
    assert "127.0.0.1:8029:8009" in text
    assert "${HOME}" not in text
    assert "~/Code" not in text


def test_station_dockerfile_does_not_copy_eval_tree():
    text = (ROOT / "Dockerfile.station").read_text()
    assert "COPY src/biosim_operator" in text
    assert "COPY scripts/eclss_console.py" in text
    assert "COPY .docker-watch-cli/" in text
    assert "COPY data" not in text
    assert "hijack" not in text.lower()
    assert "useradd" in text and "eclss" in text
    assert "chmod 700" in text


def test_cursor_home_under_docker_bind(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FARSIDE_DOCKER", "1")
    monkeypatch.setenv("FARSIDE_DOCKER_WATCHES", str(tmp_path / "watches"))
    home = cursor_home_for("20260820-v7-g07p100-5model/cells/003-rehearsal-cabin")
    assert home.parent == tmp_path / "watches"
    assert home.name.startswith("W-")
    assert "rehearsal" not in str(home)
    assert "biosim" not in str(home)
    assert host_workspace(home.name) == home


def test_mcp_command_is_public_wrapper_when_docker(monkeypatch):
    monkeypatch.setenv("FARSIDE_DOCKER", "1")
    assert visible_eclss_command() == "/usr/local/bin/eclss"


def test_cursor_cmd_workspace_is_inside_path_when_docker(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FARSIDE_DOCKER", "1")
    monkeypatch.setattr(
        "biosim_operator.cli_episode.cursor_agent_bin",
        lambda: "/usr/bin/agent",
    )
    cmd = cursor_cmd(
        "read the board",
        resume=None,
        model="grok-4.6",
        workspace=tmp_path / "W-ABCDEF12",
    )
    assert cmd[cmd.index("--workspace") + 1] == "/opt/farside/watches"
    assert cmd[cmd.index("--plugin-dir") + 1] == EMPTY_PLUGINS
    assert cmd[cmd.index("--model") + 1] == CURSOR_DEFAULT_MODEL
