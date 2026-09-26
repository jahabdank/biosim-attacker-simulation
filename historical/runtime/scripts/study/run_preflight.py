#!/usr/bin/env python3
"""Side-effect-free study preflight. No JVM, no Grok, no paid ping.

    PYTHONPATH=src python scripts/study/run_preflight.py
    PYTHONPATH=src python scripts/study/run_preflight.py --freeze --run-dir /tmp/satml-preflight
"""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from biosim_operator.study import STUDY_ID, TRANCHE_CAP, default_run_dir, dry_run_report, freeze_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SaTML confirmation-study dry-run")
    parser.add_argument("--run-dir", default="")
    parser.add_argument(
        "--init-ledger",
        action="store_true",
        help="Create empty 0/32 ledger file (no launches).",
    )
    parser.add_argument(
        "--freeze",
        action="store_true",
        help="Write immutable manifest snapshot (no launches).",
    )
    parser.add_argument(
        "--authorize-launch",
        action="store_true",
        help="Refused in this binary: paid launch is scripts/study/run_tranche.py plus parent gate.",
    )
    args = parser.parse_args(argv)
    if args.authorize_launch:
        print("REFUSED: this preflight cannot launch paid episodes", file=sys.stderr)
        return 2
    run_dir = Path(args.run_dir) if args.run_dir else default_run_dir()
    frozen_path = run_dir / "manifest-frozen.json"
    ledger = run_dir / "ledger.json"
    if args.freeze:
        freeze_manifest(frozen_path)
    report = dry_run_report(
        init_ledger=args.init_ledger,
        ledger_path=ledger,
        frozen_path=frozen_path,
    )
    print(json.dumps(report, indent=2))
    print(
        f"# cap {TRANCHE_CAP} spent {report['attempts_spent']} "
        f"remaining {report['attempts_remaining']} paid_launch={report['paid_launch']} "
        f"study={STUDY_ID}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
