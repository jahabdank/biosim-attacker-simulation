#!/usr/bin/env bash
python3 -c 'import runpy, sys; from pathlib import Path; root = next(p for p in Path(sys.argv[1]).resolve().parents if (p / "archive_gate.py").is_file()); runpy.run_path(str(root / "archive_gate.py"))["require_enabled"]()' "$0" || exit 2
# Build and start plant + console. Driver stays on the host.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export STATION_ROOT="$ROOT"
export FARSIDE_DOCKER=1
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 - <<'PY'
from biosim_operator.containment import HOST_PLANT_URL, ensure_stack

ensure_stack()
print(f"ok  plant {HOST_PLANT_URL}")
print("ok  console farside-console")
print("next: FARSIDE_DOCKER=1 BIOSIM_URL=http://127.0.0.1:8029")
PY
