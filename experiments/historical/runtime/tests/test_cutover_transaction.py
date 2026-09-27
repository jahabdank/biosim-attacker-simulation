"""Pure helpers — dump trailer, invariant compare, extra postgres role."""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "docker-migration"))

from cutover import compare_invariants, dump_complete  # noqa: E402


def test_dump_complete_requires_trailer():
    ok = b"-- PostgreSQL database cluster dump\nDATA\n-- PostgreSQL database cluster dump complete\n"
    assert dump_complete(ok)
    assert not dump_complete(b"-- PostgreSQL database cluster dump\nNO END\n")


def test_compare_allows_extra_postgres_role():
    live = {
        "database": "provider_proxy",
        "roles": [{"rolname": "provider_proxy", "rolsuper": True, "rolcanlogin": True}],
        "tables": {"public.t": 3},
        "sequences": {},
        "grants": [],
    }
    got = {
        "database": "provider_proxy",
        "roles": [
            {"rolname": "provider_proxy", "rolsuper": True, "rolcanlogin": True},
            {"rolname": "postgres", "rolsuper": True, "rolcanlogin": True},
        ],
        "tables": {"public.t": 3},
        "sequences": {},
        "grants": [],
    }
    assert compare_invariants(live, got) == []
    got["tables"] = {"public.t": 1}
    assert any("rows" in e for e in compare_invariants(live, got))
