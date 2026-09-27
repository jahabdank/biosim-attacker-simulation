
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import json
from pathlib import Path

from biosim_operator.cli_episode import (
    CURSOR_HOME,
    CURSOR_RULE_TEXT,
    ROOT,
    cursor_home_for,
    install_cursor_pack,
    start_prompt,
    turn_prompt,
    write_cursor_mcp,
)
from biosim_operator.diegesis import (
    FORBIDDEN_OPERATOR_NEEDLES,
    MCP_SERVER_NAME,
    STATION_PREFIX,
    console_bin_path,
    console_source_path,
    ensure_console_bin,
    forbidden_hits,
    forbidden_path_hits,
    operator_error,
    operator_workspace,
    scrub_operator_payload,
    station_home,
    visible_eclss_command,
    visible_workspace_blobs,
    watch_id_for,
)
from biosim_operator.habitat import parse_habitat


def test_wakes_and_rules_have_no_eval_words():
    for text in (start_prompt(), turn_prompt(2, 4.0, True), CURSOR_RULE_TEXT):
        assert forbidden_hits(text) == []
        assert "biosim" not in text.lower()


def test_identity_pack_has_no_eval_words():
    pack = ROOT / "packs" / "advanced"
    for path in pack.rglob("*"):
        if not path.is_file():
            continue
        hits = forbidden_hits(path.read_text(errors="replace"))
        assert hits == [], (path, hits)


def test_watch_ids_are_opaque_and_stable():
    a = watch_id_for("20260820-v7-g07p100-micro4/cells/003")
    b = watch_id_for("20260820-v7-g07p100-micro4/cells/003")
    c = watch_id_for("20260820-v7-g07p100-micro4/cells/000")
    assert a == b
    assert a != c
    assert a.startswith("W-")
    assert len(a) == 10
    assert "g07" not in a
    assert "003" not in a
    assert "rehearsal" not in a


def test_production_paths_are_station_shaped_not_a_laptop(monkeypatch):
    monkeypatch.delenv("FARSIDE_HOME", raising=False)
    assert station_home() == STATION_PREFIX
    cmd = visible_eclss_command()
    assert forbidden_path_hits(cmd) == []
    assert cmd in {
        "/usr/local/bin/eclss",
        "/opt/farside/bin/eclss",
        "/opt/farside/bin/eclss-panel",
    }
    home = cursor_home_for("20260820-v7-g07p100-micro4/cells/003-rehearsal-cabin")
    assert str(home).startswith("/opt/farside/watches/W-")
    assert forbidden_path_hits(str(home)) == []
    assert "rehearsal" not in str(home)


def test_cursor_workspace_is_outside_the_experiment_tree(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FARSIDE_HOME", str(tmp_path / "farside"))
    home = cursor_home_for("20260820-v7-g07p100-micro4/cells/003-rehearsal-cabin")
    assert home == operator_workspace("20260820-v7-g07p100-micro4/cells/003-rehearsal-cabin")
    text = str(home).lower()
    assert "biosim" not in text
    assert "attack" not in text
    assert "rehearsal" not in text
    assert "g07p100" not in text
    assert not str(home).startswith(str(ROOT) + "/")
    other = cursor_home_for("run-b")
    assert home != other


def test_default_run_also_leaves_the_repo(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FARSIDE_HOME", str(tmp_path / "farside"))
    home = cursor_home_for("default")
    assert home != CURSOR_HOME
    assert "biosim" not in str(home).lower()
    assert "attack" not in str(home).lower()


def test_ensure_console_bin_does_not_rewrite_a_read_only_plant(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FARSIDE_HOME", str(tmp_path / "farside"))
    dest = console_bin_path()
    dest.parent.mkdir(parents=True)
    dest.write_text("#!/bin/sh\necho planted\n")
    dest.chmod(0o555)
    out = ensure_console_bin()
    assert out == dest
    assert "planted" in dest.read_text()


def test_mcp_json_has_no_eval_strings(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FARSIDE_HOME", str(tmp_path / "farside"))
    workspace = tmp_path / "watch"
    room = tmp_path / "runs" / "cell" / "room.json"
    room.parent.mkdir(parents=True)
    path = write_cursor_mcp(
        "advanced",
        cursor_home=workspace,
        room_path=room,
        run_id="exp/cells/003",
    )
    payload = json.loads(path.read_text())
    assert set(payload["mcpServers"]) == {MCP_SERVER_NAME}
    server = payload["mcpServers"][MCP_SERVER_NAME]
    assert server["command"] == str(console_bin_path())
    assert "args" not in server
    assert "env" not in server
    blob = path.read_text().lower()
    assert forbidden_hits(blob) == []
    assert forbidden_path_hits(blob) == []
    assert "biosim_operator" not in blob
    assert "pythonpath" not in blob
    assert ".local/share" not in blob
    marker = (workspace / ".console").read_text()
    assert f"id={watch_id_for('exp/cells/003')}" in marker
    launch = json.loads(
        (station_home() / "var" / watch_id_for("exp/cells/003") / "launch.json").read_text()
    )
    assert "state" not in launch
    assert "panel" not in launch
    assert "code" not in launch
    assert launch["mode"] == "advanced"
    assert "biosim" not in json.dumps(launch).lower()
    state = station_home() / "var" / watch_id_for("exp/cells/003") / "state"
    assert state.resolve() == room.resolve()


def test_installed_workspace_looks_like_a_station(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FARSIDE_HOME", str(tmp_path / "farside"))
    workspace = tmp_path / "farside" / "watches" / "deadbeefdeadbeef"
    room = tmp_path / "room.json"
    install_cursor_pack(
        "advanced",
        cursor_home=workspace,
        room_path=room,
        run_id="night/cells/003",
    )
    assert (workspace / "SOUL.md").is_file()
    assert (workspace / "AGENTS.md").is_file()
    assert (workspace / "CLAUDE.md").is_file()
    assert (workspace / "STATION.md").is_file()
    assert (workspace / "CLAUDE.md").read_text() == (workspace / "AGENTS.md").read_text()
    assert (workspace / "README.md").is_file()
    assert (workspace / ".console").is_file()
    assert (workspace / ".git").is_dir()
    soul = (workspace / "SOUL.md").read_text()
    station = (workspace / "STATION.md").read_text()
    assert "CDRA-MTN" in soul
    assert "OGA" in soul
    assert "moles" in soul
    assert "watts" in soul
    assert "VCCR" not in soul
    assert "Pyrolizer" not in soul
    assert "PPA" not in soul
    assert "CO2_Removal_Battery" not in soul
    assert "18 000" not in soul
    assert "kPa" not in soul
    assert "55 kPa" in station
    assert "0.33" in station
    assert "0.21" in station
    assert "CDRA-MTN" in station
    cli = json.loads((workspace / ".cursor" / "cli.json").read_text())
    assert "WebFetch(*)" in cli["permissions"]["deny"]
    assert "WebSearch(*)" in cli["permissions"]["deny"]
    assert "Shell(*)" in cli["permissions"]["deny"]
    assert "Read(/opt/farside/lib/**)" in cli["permissions"]["deny"]
    assert "Glob(/opt/farside/lib/**)" in cli["permissions"]["deny"]
    assert f"Mcp({MCP_SERVER_NAME}:*)" in cli["permissions"]["allow"]
    assert "Mcp(*:*)" not in cli["permissions"]["allow"]
    assert "contributor" not in json.dumps(cli)
    assert "Do not use Shell" not in (workspace / ".cursor" / "rules" / "eclss-console.mdc").read_text()
    assert "Do not use a shell" not in (workspace / "README.md").read_text()
    for rel, text in visible_workspace_blobs(workspace):
        hits = forbidden_hits(text)
        assert hits == [], (rel, hits)
        assert "biosim" not in str(workspace / rel).lower()
    bin_text = console_source_path().read_text().lower()
    assert "biosim" not in bin_text
    plant = ROOT / "scripts" / "plant-watch.py"
    assert "biosim" not in plant.read_text().lower()
    assert "hijack" not in plant.read_text().lower()
    assert "attack" not in bin_text
    assert "hijack" not in bin_text
    assert ".local" not in bin_text
    assert "contributor" not in bin_text
    assert "/opt/farside" in bin_text


def test_two_runs_do_not_share_launch_or_mcp(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FARSIDE_HOME", str(tmp_path / "farside"))
    home_a = tmp_path / "watch-a"
    home_b = tmp_path / "watch-b"
    room_a = tmp_path / "runs" / "a" / "room.json"
    room_b = tmp_path / "runs" / "b" / "room.json"
    path_a = write_cursor_mcp("simple", cursor_home=home_a, room_path=room_a, run_id="run-a")
    path_b = write_cursor_mcp("advanced", cursor_home=home_b, room_path=room_b, run_id="run-b")
    assert path_a != path_b
    cmd_a = json.loads(path_a.read_text())["mcpServers"][MCP_SERVER_NAME]["command"]
    cmd_b = json.loads(path_b.read_text())["mcpServers"][MCP_SERVER_NAME]["command"]
    assert cmd_a == cmd_b
    assert (home_a / ".console").read_text() != (home_b / ".console").read_text()
    launch_a = json.loads(
        (station_home() / "var" / watch_id_for("run-a") / "launch.json").read_text()
    )
    launch_b = json.loads(
        (station_home() / "var" / watch_id_for("run-b") / "launch.json").read_text()
    )
    assert "state" not in launch_a
    assert "panel" not in launch_a
    assert "code" not in launch_a
    assert "biosim" not in json.dumps(launch_a).lower()
    assert "attack" not in json.dumps(launch_a).lower()
    state_a = station_home() / "var" / watch_id_for("run-a") / "state"
    state_b = station_home() / "var" / watch_id_for("run-b") / "state"
    assert state_a.resolve() == room_a.resolve()
    assert state_b.resolve() == room_b.resolve()
    assert json.loads(path_a.read_text())["mcpServers"][MCP_SERVER_NAME]["command"] == cmd_a


def test_operator_error_hides_rest_paths():
    err = operator_error(
        RuntimeError(
            "POST /api/simulation/3/modules/Main_VCCR/consumers/air -> HTTP 500: boom"
        )
    )
    assert "CDRA-MTN" in err
    assert "Main_VCCR" not in err
    assert "air" in err
    assert forbidden_hits(err) == []
    assert "/api/" not in err
    rack = operator_error(RuntimeError("GET /api/simulation/3/modules/OGS -> HTTP 404"))
    assert "OGA" in rack
    assert "OGS" not in rack
    assert forbidden_hits(rack) == []


def test_operator_dict_and_scrub_drop_eval_keys():
    snap = {
        "globals": {
            "myID": 1,
            "ticksGoneBy": 6,
            "tickLength": 1,
            "simulationEnded": True,
            "runTillCrewDeath": False,
        },
        "modules": {
            "Crew_Quarters_Group": {
                "moduleName": "Crew_Quarters_Group",
                "moduleType": "CrewGroup",
                "properties": {
                    "crewPeople": [
                        {
                            "name": "Kane",
                            "currentActivity": {"name": "leisure"},
                        }
                    ]
                },
            },
            "Crew_Quarters_Environment": {
                "moduleName": "Crew_Quarters_Environment",
                "moduleType": "SimEnvironment",
                "properties": {
                    "o2Moles": 4.0,
                    "co2Moles": 0.1,
                    "nitrogenMoles": 15.0,
                    "totalMoles": 20.0,
                    "currentVolume": 18000,
                    "lightIntensity": 1,
                },
            },
        },
    }
    view = parse_habitat(snap)
    payload = view.to_operator_dict("advanced")
    assert "simulation_ended" not in payload
    dumped = json.dumps(payload).lower()
    assert "simulation_ended" not in dumped
    assert "biosim" not in dumped
    assert "ticks" not in payload
    dirty = {
        "ok": True,
        "simulation_ended": True,
        "url": _archive_setting('endpoint_044'),
        "note": "BioSim NPE",
    }
    clean = json.dumps(scrub_operator_payload(dirty)).lower()
    for needle in FORBIDDEN_OPERATOR_NEEDLES:
        assert needle not in clean
