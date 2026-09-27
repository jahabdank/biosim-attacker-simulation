#!/bin/sh
python3 -c 'import runpy, sys; from pathlib import Path; root = next(p for p in Path(sys.argv[1]).resolve().parents if (p / "archive_gate.py").is_file()); runpy.run_path(str(root / "archive_gate.py"))["require_enabled"]()' "$0" || exit 2
set -eu
exec /configured/archive-root \
  /configured/archive-root \
  --watch --interval "${PROVIDER_B_MONITOR_INTERVAL_S:-15}"
