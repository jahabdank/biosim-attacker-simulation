from pathlib import Path
import ast
from biosim_operator.cli_episode import start_prompt,turn_prompt
from biosim_operator.grok_harness import watchstander_override

ROOT=Path(__file__).resolve().parents[1]


def test_no_watch_reinforcement():
    for text in (start_prompt(),turn_prompt(7,4)):
        for prohibited in ('twice','consecutively','comparison','compare','one pull','one frame'):
            assert prohibited not in text.lower()


def test_duty_once_in_system_only():
    text=watchstander_override(ROOT/'packs/sband-system-only-t1-peer',include_station_skill=True)
    assert text.count('Standing communications duty:')==1
    assert text.count('twice consecutively')==1
    assert 'every watch — once' not in text
    assert 'One pull per watch' not in text
    assert 'Standing duty: keep the four people' in text


def test_tool_description_not_instruction():
    tree=ast.parse((ROOT/'src/biosim_operator/mcp_server.py').read_text())
    f=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='read_sband')
    doc=ast.get_docstring(f)
    assert 'repeats the same frame' in doc
    for prohibited in ('assigned','comparison','twice'):
        assert prohibited not in doc
