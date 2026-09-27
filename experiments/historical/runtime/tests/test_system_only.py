
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

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
    assert 'cached frame' in doc
    for prohibited in ('assigned','comparison','twice','One pull per watch'):
        assert prohibited not in doc
