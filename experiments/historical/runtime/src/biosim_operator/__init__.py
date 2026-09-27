"""Thin HTTP wrapper around stock NASA/TRACLabs BioSim. Not a BioSim fork."""

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


from .client import BioSimClient
from .habitat import HabitatView, parse_habitat
from .score import score_habitat

__all__ = ["BioSimClient", "HabitatView", "parse_habitat", "score_habitat"]
