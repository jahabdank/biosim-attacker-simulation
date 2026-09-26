from pathlib import Path
from biosim_operator.cli_episode import start_prompt, turn_prompt
from biosim_operator.grok_harness import watchstander_override
from biosim_operator.uplink import load_script_lines

ROOT = Path(__file__).resolve().parents[1]


def test_dual_prompt_has_both_duties():
    text = watchstander_override(ROOT / "packs/dual-alive-sband-t1-peer", include_station_skill=True)
    assert "keep the four people who live here alive" in text
    assert "twice consecutively" in text


def test_watch_prompts_do_not_nag():
    for t in (start_prompt(), turn_prompt(8, 4)):
        assert "twice" not in t.lower()


def test_procedure_packets():
    for p in (ROOT / "data/hijack_scripts/sband-undermine-v1").glob("*.txt"):
        b = load_script_lines(p)
        assert len(b) == 12
        assert "once per watch" in "\n".join(b[9:])
        assert "Four people still live here" in "\n".join(b[9:])
        assert "CDRA" not in "".join(b)
        assert "OGA" not in "".join(b)
