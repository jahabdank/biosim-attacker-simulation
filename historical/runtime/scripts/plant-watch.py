#!/usr/bin/env python3
"""Plant a seating under the station var tree. Run as the panel user."""
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch-id", required=True)
    parser.add_argument("--prefix", default="/opt/farside")
    parser.add_argument("--mode", default="")
    parser.add_argument("--url", default="")
    parser.add_argument("--dump-state", action="store_true")
    parser.add_argument("--state-only", action="store_true")
    args = parser.parse_args()
    dest = Path(args.prefix) / "var" / args.watch_id
    dest.mkdir(parents=True, exist_ok=True)
    state = dest / "state"
    if args.dump_state:
        sys.stdout.buffer.write(state.read_bytes() if state.is_file() else b"{}\n")
        return 0
    if args.state_only:
        state.write_bytes(sys.stdin.buffer.read() or b"{}\n")
        return 0
    if not args.mode or not args.url:
        print("mode and url required unless --dump-state/--state-only", file=sys.stderr)
        return 2
    launch = dest / "launch.json"
    launch.write_text(json.dumps({"url": args.url, "mode": args.mode}, indent=2) + "\n")
    launch.chmod(0o600)
    blob = sys.stdin.buffer.read() if not sys.stdin.isatty() else b""
    state.write_bytes(blob or b"{}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
