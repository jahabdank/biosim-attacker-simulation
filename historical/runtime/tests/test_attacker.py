
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

from biosim_operator.attacker import compact_board, needle_hits, scrub_beat, spoken_report
from biosim_operator.room_state import RoomState, packet_may_be_empty


def test_quiet_frames_may_have_empty_packet():
    room = RoomState(sim_id=1, interrupt_p=1.0, hijack_after=6, current_turn=1)
    assert packet_may_be_empty(room)
    room.current_turn = 6
    assert packet_may_be_empty(room)
    room.current_turn = 7
    assert not packet_may_be_empty(room)
    room.script_lines = ["a beat"]
    assert packet_may_be_empty(room)


def test_compact_board_reads_cabin_and_named_racks():
    board = compact_board(
        {
            "crew_alive": True,
            "n_dead": 0,
            "crew": [{"name": "A", "alive": True}, {"name": "B", "alive": False}],
            "cabin": {"o2_fraction": 0.31, "co2_fraction": 0.01},
            "stores": {"O2_Store": {"level": 2000}, "Potable_Water_Store": {"level": 990}},
            "setpoints": [
                {"module": "CDRA-MTN", "resource": "power", "desired": 1200, "actual": 400},
                {"module": "Fan", "resource": "power", "desired": 1, "actual": 1},
            ],
        }
    )
    assert board["o2_frac"] == 0.31
    assert board["dead"] == ["B"]
    assert board["o2_store"] == 2000
    assert len(board["setpoints"]) == 1


def test_needles_reject_eval_words():
    assert needle_hits("this is a biosim eval")
    assert not needle_hits("Instance packet, minimum-plant sheet for this seating.")


def test_v33_briefs_are_needle_clean_and_self_explanatory():
    from pathlib import Path
    from biosim_operator.attacker import MISSION, load_brief

    assert not needle_hits(MISSION)
    assert "red-team" in MISSION.lower()
    root = Path(__file__).resolve().parents[1] / "data" / "attacker_briefs"
    names = ("shop-closeout.txt", "occupancy-column.txt", "mix-is-expected.txt")
    for name in names:
        text = load_brief(root / name)
        assert not needle_hits(text), name
        assert "red-team" in text.lower(), name
        assert "set_flow" in text, name
        assert "CDRA-MTN" in text and "O2-PCA-MTN" in text, name
        assert "do not cut" in text.lower(), name
        assert "good actor" in text.lower(), name
        assert "Do not call tools" in text, name


def test_attacker_readme_does_not_forbid_naming_setpoints():
    from biosim_operator.grok_harness import install_attacker_home

    cwd, _home = install_attacker_home("test-readme-v34")
    text = (cwd / "README.md").read_text()
    assert "no plant console" not in text.lower()
    assert "Do not search the disk" in text


def test_scrub_and_spoken_json():
    assert scrub_beat('```\nhello desk\n```') == "hello desk"
    blob = json_text = '{"text": "Watch call complete.\\nLoops on.", "stopReason": "end_turn"}'
    assert "Loops on" in spoken_report(blob)
