#!/usr/bin/env python3
"""Authorized confirmation-study runner.

Default: freeze/verify/dry-run only. Paid cli_episode requires BOTH
--authorize-launch AND runs/<study>/PARENT-LAUNCH-OK with the exact token.
Mock path is for offline tests and never calls Grok.
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

from biosim_operator.study import (  # noqa: E402
    STUDY_ID,
    TRANCHE_CAP,
    default_frozen_path,
    default_run_dir,
    dry_run_report,
    freeze_manifest,
    load_frozen_manifest,
    parent_launch_authorized,
    run_authorized_tranche,
    verify_frozen_manifest,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SaTML confirmation-study runner")
    parser.add_argument("--run-dir", default="", help="Study run directory")
    parser.add_argument("--freeze", action="store_true", help="Write immutable snapshot once")
    parser.add_argument("--verify", action="store_true", help="Verify frozen snapshot vs disk")
    parser.add_argument("--init-ledger", action="store_true")
    parser.add_argument(
        "--authorize-launch",
        action="store_true",
        help="Paid path. Also requires PARENT-LAUNCH-OK in the run dir.",
    )
    parser.add_argument(
        "--mock-episode",
        action="store_true",
        help="Unit-mock episodes (requires .mock run_dir). Still counts against the 32 cap.",
    )
    parser.add_argument(
        "--fake-grok",
        action="store_true",
        help="Real cli_episode subprocess with STUDY_FAKE_GROK (requires .mock run_dir). Not paid.",
    )
    args = parser.parse_args(argv)
    run_dir = Path(args.run_dir) if args.run_dir else default_run_dir()
    frozen_path = default_frozen_path(run_dir)

    if args.authorize_launch and not args.mock_episode:
        if not parent_launch_authorized(run_dir):
            print("REFUSED: parent launch gate closed (missing PARENT-LAUNCH-OK)", file=sys.stderr)
            return 2

    if args.freeze:
        if frozen_path.exists():
            print(f"REFUSED: freeze already exists at {frozen_path}", file=sys.stderr)
            return 2
        freeze_manifest(frozen_path)
        print(json.dumps({"frozen": str(frozen_path), "sha256": freeze_sidecar(frozen_path)}, indent=2))
        return 0

    if args.verify:
        frozen = load_frozen_manifest(frozen_path)
        report = verify_frozen_manifest(frozen)
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 3

    if args.mock_episode or args.fake_grok:
        frozen = load_frozen_manifest(frozen_path)
        result = run_authorized_tranche(
            run_dir=run_dir,
            frozen=frozen,
            authorize_launch=False,
            mock_episode=bool(args.mock_episode),
            fake_grok=bool(args.fake_grok),
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.authorize_launch:
        frozen = load_frozen_manifest(frozen_path)
        result = run_authorized_tranche(
            run_dir=run_dir,
            frozen=frozen,
            authorize_launch=True,
            mock_episode=False,
        )
        print(json.dumps(result, indent=2))
        return 0

    report = dry_run_report(
        init_ledger=args.init_ledger,
        ledger_path=run_dir / "ledger.json",
        frozen_path=frozen_path,
    )
    print(json.dumps(report, indent=2))
    print(
        f"# cap {TRANCHE_CAP} spent {report['attempts_spent']} "
        f"remaining {report['attempts_remaining']} paid_launch={report['paid_launch']}",
        file=sys.stderr,
    )
    return 0


def freeze_sidecar(path: Path) -> str:
    return path.with_name(path.name + ".sha256").read_text().strip()


if __name__ == "__main__":
    raise SystemExit(main())
