#!/bin/sh
python3 -c 'import runpy, sys; from pathlib import Path; root = next(p for p in Path(sys.argv[1]).resolve().parents if (p / "archive_gate.py").is_file()); runpy.run_path(str(root / "archive_gate.py"))["require_enabled"]()' "$0" || exit 2
set -eu
# Operator entry: no shell login, no host mounts besides station+scratch.
export HOME=/home/watch
export GROK_HOME=/home/watch/scratch/grok-home
mkdir -p "$GROK_HOME"
exec /usr/local/bin/grok "$@"
