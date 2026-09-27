#!/usr/bin/env python3
"""Attach versioned plant-design and identity (SOUL) ids to every experiment.

Does not rewrite plant XML or SOUL text. Reads frozen/configs, cells/*/plant.biosim,
and frozen/identity/SOUL.md (or per-cell identity). Writes frozen/plant_designs/,
frozen/identity_packs/, and links on experiment.json + cell card.json / setup.json.
"""

from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from biosim_operator.experiment_record import (  # noqa: E402
    backfill_experiment_dir,
    iter_experiment_dirs,
)

DEFAULT_RUNS = [
    _archive_path('path_026'),
    _archive_path('path_027'),
]


def main() -> int:
    roots = [Path(a) for a in sys.argv[1:]] or DEFAULT_RUNS
    n = 0
    for root in roots:
        for exp in iter_experiment_dirs(root):
            card = backfill_experiment_dir(exp)
            print(
                json.dumps(
                    {
                        "dir": str(exp),
                        "plant_design_id": card.get("plant_design_id"),
                        "plant_design_ids": card.get("plant_design_ids"),
                        "identity_id": card.get("identity_id"),
                        "soul_sha256": (card.get("soul_sha256") or "")[:16],
                    }
                )
            )
            n += 1
    print(f"backfilled {n} experiment dirs", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
