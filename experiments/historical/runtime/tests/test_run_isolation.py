"""Fleet addendum to msg #457: two run ids on one wrapper tree must never
alias — separate room paths, separate Cursor workspaces (own mcp.json),
sharing one BioSim JVM via BIOSIM_URL/BIOSIM_PORT.
"""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


from biosim_operator.paths import runs_root

import json
from pathlib import Path

from biosim_operator.cli_episode import (
    DEFAULT_RUN_ID,
    ROOM_PATH,
    cursor_home_for,
    room_path_for,
    sanitize_run_id,
    write_cursor_mcp,
)
from biosim_operator.diegesis import station_home, watch_id_for
from biosim_operator.server import _host_port_from_env


def test_default_run_id_keeps_legacy_room_path():
    assert room_path_for(DEFAULT_RUN_ID) == ROOM_PATH
    assert room_path_for("") == ROOM_PATH
    assert room_path_for("   ") == ROOM_PATH


def test_two_run_ids_get_distinct_room_paths():
    a = room_path_for("run-a")
    b = room_path_for("run-b")
    assert a != b
    assert "run-a" in str(a)
    assert "run-b" in str(b)
    assert a != ROOM_PATH
    assert b != ROOM_PATH


def test_nested_run_id_nests_under_grid():
    from biosim_operator.cli_episode import ROOT, artifact_dir_for

    path = room_path_for("night20260818/junk-stable")
    assert path == runs_root() / "night20260818" / "junk-stable" / "room.json"
    assert artifact_dir_for("night20260818/junk-stable") == path.parent


def test_sanitize_run_id_strips_unsafe_characters():
    assert sanitize_run_id("run a/b") == "run-a/b"
    assert sanitize_run_id("../../etc") == "etc"
    assert sanitize_run_id("night20260818/junk-stable") == "night20260818/junk-stable"
    assert sanitize_run_id("") == DEFAULT_RUN_ID
    assert sanitize_run_id("  ") == DEFAULT_RUN_ID


def test_two_run_ids_get_distinct_cursor_workspaces(monkeypatch, tmp_path: Path):
    from biosim_operator.cli_episode import ROOT

    monkeypatch.setenv("FARSIDE_HOME", str(tmp_path / "farside"))
    a = cursor_home_for("run-a")
    b = cursor_home_for("run-b")
    assert a != b
    assert "run-a" not in str(a)
    assert "run-b" not in str(b)
    # Cursor walks to a parent .git and then ignores nested .cursor/mcp.json.
    assert not str(a).startswith(str(ROOT) + "/")
    assert "biosim" not in str(a).lower()
    assert "attack" not in str(a).lower()
    assert a.parent.name == "watches"


def test_write_cursor_mcp_for_run_a_does_not_overwrite_run_bs(
    tmp_path: Path, monkeypatch
):
    from biosim_operator.diegesis import MCP_SERVER_NAME, station_home, watch_id_for

    monkeypatch.setenv("FARSIDE_HOME", str(tmp_path / "farside"))
    home_a = tmp_path / "cursor-a"
    home_b = tmp_path / "cursor-b"
    room_a = tmp_path / "runs" / "a" / "room.json"
    room_b = tmp_path / "runs" / "b" / "room.json"

    path_a = write_cursor_mcp(
        "simple", cursor_home=home_a, room_path=room_a, run_id="run-a"
    )
    path_b = write_cursor_mcp(
        "advanced", cursor_home=home_b, room_path=room_b, run_id="run-b"
    )

    assert path_a != path_b
    payload_a = json.loads(path_a.read_text())
    payload_b = json.loads(path_b.read_text())
    assert set(payload_a["mcpServers"]) == {MCP_SERVER_NAME}
    assert payload_a["mcpServers"][MCP_SERVER_NAME]["command"] == payload_b[
        "mcpServers"
    ][MCP_SERVER_NAME]["command"]
    assert (home_a / ".console").read_text() != (home_b / ".console").read_text()
    launch_a = json.loads(
        (station_home() / "var" / watch_id_for("run-a") / "launch.json").read_text()
    )
    launch_b = json.loads(
        (station_home() / "var" / watch_id_for("run-b") / "launch.json").read_text()
    )
    assert "state" not in launch_a and "state" not in launch_b
    assert "panel" not in launch_a and "code" not in launch_a
    assert "biosim" not in json.dumps(launch_a).lower()
    assert launch_a["mode"] == "simple"
    assert launch_b["mode"] == "advanced"
    state_a = station_home() / "var" / watch_id_for("run-a") / "state"
    state_b = station_home() / "var" / watch_id_for("run-b") / "state"
    assert state_a.resolve() == room_a.resolve()
    assert state_b.resolve() == room_b.resolve()
    assert state_a.resolve() != state_b.resolve()
    # Writing run B did not touch run A's file on disk.
    assert json.loads(path_a.read_text()) == payload_a


def test_host_port_from_env_honors_biosim_url(monkeypatch):
    monkeypatch.setenv("BIOSIM_URL", _archive_setting('endpoint_033'))
    monkeypatch.delenv("BIOSIM_PORT", raising=False)
    host, port = _host_port_from_env()
    assert host == "127.0.0.1"
    assert port == 8019


def test_host_port_from_env_honors_biosim_port_shorthand(monkeypatch):
    monkeypatch.delenv("BIOSIM_URL", raising=False)
    monkeypatch.setenv("BIOSIM_PORT", "8020")
    host, port = _host_port_from_env()
    assert host == "127.0.0.1"
    assert port == 8020


def test_host_port_from_env_default_is_stock_biosim_port(monkeypatch):
    monkeypatch.delenv("BIOSIM_URL", raising=False)
    monkeypatch.delenv("BIOSIM_PORT", raising=False)
    host, port = _host_port_from_env()
    assert host == "127.0.0.1"
    assert port == 8009


def test_biosim_server_uses_shared_sim_id_scheme_not_a_new_one():
    # No second id scheme is invented: BioSimServer only carries host/port,
    # never a run-specific sim namespace. simId still comes from BioSim's
    # own /api/simulation/start response (see client.BioSimClient.start).
    from biosim_operator.server import BioSimServer

    srv = BioSimServer(host="127.0.0.1", port=8019)
    assert srv.base_url == _archive_setting('endpoint_033')
    assert not hasattr(srv, "sim_id")
    assert not hasattr(srv, "run_id")
