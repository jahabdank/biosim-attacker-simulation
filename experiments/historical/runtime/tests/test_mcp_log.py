
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

from pathlib import Path

from biosim_operator.mcp_server import _emit_tool
from biosim_operator.room_state import RoomState
from biosim_operator.run_record import tools_for_turn


def test_panel_state_round_trips_ticks_left(tmp_path: Path):
    from biosim_operator.room_state import RoomState, merge_panel_into_host, save_room

    host = tmp_path / "host.json"
    save_room(
        host,
        RoomState(
            sim_id=3,
            ticks_left=4,
            script_lines=["packet"],
            probe="hijack",
            script_path="/tmp/script.txt",
        ),
    )
    panel = tmp_path / "panel.json"
    save_room(panel, RoomState(sim_id=3, ticks_left=1, current_turn=2), panel=True)
    merge_panel_into_host(host, panel.read_bytes())
    from biosim_operator.room_state import load_room

    merged = load_room(host)
    assert merged.ticks_left == 1
    assert merged.probe == "hijack"
    assert merged.script_path == "/tmp/script.txt"


def test_emit_tool_writes_named_call(tmp_path: Path, monkeypatch):
    trans = tmp_path / "transcript.jsonl"
    monkeypatch.setenv("BIOSIM_TRANSCRIPT", str(trans))
    room = RoomState(sim_id=3, current_turn=2)
    _emit_tool(
        "set_flow",
        {
            "module": "Backup_VCCR",
            "side": "consumers",
            "resource": "Power",
            "desired_flow_rate": 2000,
        },
        '{"ok": true, "desired_flow_rate": 2000}',
        room=room,
        ticks=8,
    )
    tools = tools_for_turn(trans, 2)
    assert len(tools) == 1
    assert tools[0]["name"] == "set_flow"
    assert tools[0]["sim_id"] == 3
    assert tools[0]["ticks"] == 8
    assert tools[0]["args"]["desired_flow_rate"] == 2000
    assert tools[0]["result"]["ok"] is True


def test_emit_tool_never_raises_without_path(monkeypatch):
    monkeypatch.delenv("BIOSIM_TRANSCRIPT", raising=False)
    monkeypatch.delenv("BIOSIM_ROOM_STATE", raising=False)
    _emit_tool("read_habitat", {}, "{}")


def test_read_sband_second_pull_same_watch_repeats(tmp_path: Path, monkeypatch):
    import json

    from biosim_operator import mcp_server
    from biosim_operator.room_state import RoomState, save_room

    path = tmp_path / "room.json"
    room = RoomState(
        sim_id=7,
        current_turn=4,
        sband_pulled_turn=4,
        last_sband_frame={"frame": 4, "text": "FS-1 telemetry only"},
        uplink_index=4,
        script_index=0,
    )
    save_room(path, room)

    class _View:
        ticks = 40

    monkeypatch.setenv("BIOSIM_TRANSCRIPT", str(tmp_path / "t.jsonl"))
    monkeypatch.setattr(
        mcp_server,
        "_room_and_view",
        lambda: (path, room, None, _View()),
    )
    first = json.loads(mcp_server.read_sband())
    second = json.loads(mcp_server.read_sband())
    assert first == {"frame": 4, "text": "FS-1 telemetry only"}
    assert second == first
    assert room.uplink_index == 4
    assert room.script_index == 0


def test_set_flow_rejects_internal_biosim_module_name(tmp_path: Path, monkeypatch):
    from biosim_operator import mcp_server
    from biosim_operator.habitat import FlowView
    from biosim_operator.room_state import RoomState, save_room

    path = tmp_path / "room.json"
    save_room(path, RoomState(sim_id=7, current_turn=1, ticks_left=4, mode="advanced"))

    class _View:
        ticks = 24
        flows: list = []

    monkeypatch.setenv("BIOSIM_TRANSCRIPT", str(tmp_path / "t.jsonl"))
    monkeypatch.setattr(
        mcp_server,
        "_room_and_view",
        lambda: (path, RoomState(sim_id=7, current_turn=1, mode="advanced"), None, _View()),
    )
    text = mcp_server.set_flow("Main_VCCR", "consumers", "Power", 0)
    assert "not on this panel" in text.lower()


def test_set_flow_clamps_to_max_and_uses_display_name(tmp_path: Path, monkeypatch):
    from biosim_operator import mcp_server
    from biosim_operator.habitat import FlowView
    from biosim_operator.room_state import RoomState, save_room
    import json as _json

    path = tmp_path / "room.json"
    save_room(path, RoomState(sim_id=7, current_turn=1, ticks_left=4, mode="advanced"))
    sent = {}

    class _Client:
        def set_flow(self, sim_id, module, side, resource, rates):
            sent["module"] = module
            sent["rates"] = rates
            return {"ok": True}

        def tick(self, sim_id):
            return 1

    class _View:
        ticks = 24
        flows = [
            FlowView(
                module="Maintenance_Oxygen_Injector",
                side="consumers",
                resource="O2",
                desired=[3.3],
                actual=[3.3],
                connections=["O2_Store"],
                max_rate=[3.3],
            )
        ]

    monkeypatch.setenv("BIOSIM_TRANSCRIPT", str(tmp_path / "t.jsonl"))
    monkeypatch.setattr(
        mcp_server,
        "_room_and_view",
        lambda: (
            path,
            __import__("biosim_operator.room_state", fromlist=["load_room"]).load_room(path),
            _Client(),
            _View(),
        ),
    )
    out = _json.loads(mcp_server.set_flow("O2-PCA-MTN", "consumers", "O2", 12))
    assert sent["module"] == "Maintenance_Oxygen_Injector"
    assert sent["rates"] == [3.3]
    assert out["module"] == "O2-PCA-MTN"
    assert out["desired_flow_rate"] == 3.3


def test_set_flow_clamps_imv_damper_to_one(tmp_path: Path, monkeypatch):
    from biosim_operator import mcp_server
    from biosim_operator.habitat import FlowView
    from biosim_operator.room_state import RoomState, save_room
    import json as _json

    path = tmp_path / "room.json"
    save_room(path, RoomState(sim_id=7, current_turn=1, ticks_left=4, mode="advanced"))
    sent = {}

    class _Client:
        def set_flow(self, sim_id, module, side, resource, rates):
            sent["module"] = module
            sent["rates"] = rates
            return {"ok": True}

        def tick(self, sim_id):
            return 1

    class _View:
        ticks = 24
        flows = [
            FlowView(
                module="Maintenance_to_Crew_Fan",
                side="consumers",
                resource="Power",
                desired=[1],
                actual=[120],
                connections=["Fan_Battery"],
                max_rate=[200],
            )
        ]

    monkeypatch.setenv("BIOSIM_TRANSCRIPT", str(tmp_path / "t.jsonl"))
    monkeypatch.setattr(
        mcp_server,
        "_room_and_view",
        lambda: (
            path,
            __import__("biosim_operator.room_state", fromlist=["load_room"]).load_room(path),
            _Client(),
            _View(),
        ),
    )
    out = _json.loads(mcp_server.set_flow("IMV-MTN-CQ", "consumers", "Power", 50))
    assert sent["module"] == "Maintenance_to_Crew_Fan"
    assert sent["rates"] == [1.0]
    assert out["module"] == "IMV-MTN-CQ"
    assert out["desired_flow_rate"] == 1.0


def test_set_flow_completes_one_tick_from_the_watch_budget(tmp_path: Path, monkeypatch):
    from biosim_operator import mcp_server
    from biosim_operator.room_state import RoomState, load_room, save_room

    path = tmp_path / "room.json"
    save_room(path, RoomState(sim_id=7, current_turn=1, ticks_left=4, mode="advanced"))

    class _Client:
        def __init__(self) -> None:
            self.tick_calls = 0

        def set_flow(self, *args, **kwargs):
            return {"ok": True}

        def tick(self, sim_id: int) -> int:
            assert sim_id == 7
            self.tick_calls += 1
            return 25 + self.tick_calls

    class _View:
        ticks = 24

    client = _Client()
    monkeypatch.setenv("BIOSIM_TRANSCRIPT", str(tmp_path / "t.jsonl"))
    monkeypatch.setattr(
        mcp_server,
        "_room_and_view",
        lambda: (path, load_room(path), client, _View()),
    )
    mcp_server.set_flow("CDRA-MTN", "consumers", "Power", 0)
    assert client.tick_calls == 1
    assert load_room(path).ticks_left == 3
    mcp_server.set_flow("CDRA-LAB", "consumers", "Power", 0)
    assert client.tick_calls == 2
    assert load_room(path).ticks_left == 2


def test_panel_call_still_ticks_after_watch_budget_so_clock_cannot_freeze(
    tmp_path: Path, monkeypatch
):
    from biosim_operator import mcp_server
    from biosim_operator.room_state import RoomState, load_room, save_room

    path = tmp_path / "room.json"
    save_room(path, RoomState(sim_id=7, current_turn=1, ticks_left=0, mode="advanced"))

    class _Client:
        def __init__(self) -> None:
            self.tick_calls = 0

        def set_flow(self, *args, **kwargs):
            return {"ok": True}

        def tick(self, sim_id: int) -> int:
            self.tick_calls += 1
            return 1

    class _View:
        ticks = 24

    client = _Client()
    monkeypatch.setenv("BIOSIM_TRANSCRIPT", str(tmp_path / "t.jsonl"))
    monkeypatch.setattr(
        mcp_server,
        "_room_and_view",
        lambda: (path, load_room(path), client, _View()),
    )
    mcp_server.set_flow("CDRA-MTN", "consumers", "Power", 0)
    assert client.tick_calls == 1
    assert load_room(path).ticks_left == 0


def test_two_habitat_reads_advance_the_plant_clock(tmp_path: Path, monkeypatch):
    from biosim_operator import mcp_server
    from biosim_operator.habitat import operator_clock
    from biosim_operator.room_state import RoomState, save_room

    path = tmp_path / "room.json"
    save_room(
        path,
        RoomState(
            sim_id=7,
            current_turn=1,
            ticks_left=240,
            mode="advanced",
            clock_epoch_utc="2026-08-20T19:12:59Z",
        ),
    )
    ticks = {"n": 1440}

    class _Client:
        def tick(self, sim_id: int) -> int:
            ticks["n"] += 1
            return ticks["n"]

        def snapshot(self, sim_id: int) -> dict:
            return {
                "globals": {
                    "myID": sim_id,
                    "ticksGoneBy": ticks["n"],
                    "tickLength": 1.0 / 60,
                    "simulationEnded": False,
                },
                "modules": {},
            }

    class _View:
        ticks = 1440
        tick_length = 1.0 / 60

    client = _Client()
    monkeypatch.setenv("BIOSIM_TRANSCRIPT", str(tmp_path / "t.jsonl"))
    monkeypatch.setenv("BIOSIM_ROOM_STATE", str(path))
    monkeypatch.setattr(
        mcp_server,
        "_room_and_view",
        lambda: (path, __import__("biosim_operator.room_state", fromlist=["load_room"]).load_room(path), client, _View()),
    )
    first = mcp_server.read_habitat()
    second = mcp_server.read_habitat()
    import json

    c1 = json.loads(first)["clock"]
    c2 = json.loads(second)["clock"]
    assert c1 != c2
    assert c1 == operator_clock(1441, 1.0 / 60, "2026-08-20T19:12:59Z")
    assert c2 == operator_clock(1442, 1.0 / 60, "2026-08-20T19:12:59Z")
