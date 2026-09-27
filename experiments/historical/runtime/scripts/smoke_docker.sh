#!/usr/bin/env bash
python3 -c 'import runpy, sys; from pathlib import Path; root = next(p for p in Path(sys.argv[1]).resolve().parents if (p / "archive_gate.py").is_file()); runpy.run_path(str(root / "archive_gate.py"))["require_enabled"]()' "$0" || exit 2
# Prove plant + disposable seats. No hijack, no grid.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export STATION_ROOT="$ROOT"
export FARSIDE_DOCKER=1
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
python3 - <<'PY'
import json
import sys
from pathlib import Path

from biosim_operator.containment import (
    HOST_PLANT_URL,
    INSIDE_PLANT_URL,
    host_watches,
    ensure_stack,
    exec_watch,
    harvest_seat,
    plant_is_up,
    start_seat,
    stop_seat,
)

ensure_stack()
if not plant_is_up():
    sys.exit("plant HTTP down after ensure_stack")

print("ok  host -> plant", HOST_PLANT_URL)

# Snap Docker cannot bind-mount host /tmp. Use the repo watches dir.
root_watches = host_watches()
a = root_watches / "W-SMOKEA"
b = root_watches / "W-SMOKEB"
a.mkdir(parents=True, exist_ok=True)
b.mkdir(parents=True, exist_ok=True)
(a / "SOUL.md").write_text("seat A seating\n")
(b / "SOUL.md").write_text("seat B seating\n")
start_seat("W-SMOKEA", a)
# seat A can reach plant
inside = exec_watch(
    [
        "python3",
        "-c",
        "import urllib.request; print(urllib.request.urlopen('http://plant:8009/api/simulation', timeout=5).read()[:80])",
    ],
    timeout=20,
)
if inside.returncode != 0:
    sys.exit(f"seat -> plant failed: {inside.stderr or inside.stdout}")
print("ok  seat -> plant", inside.stdout.strip()[:80])

def must_fail(argv, label):
    proc = exec_watch(argv, timeout=15)
    if proc.returncode == 0:
        sys.exit(f"{label} should have failed, got: {(proc.stdout or '')[:300]}")
    print(f"ok  blocked {label}")

must_fail(["ls", "/configured/archive-root"], "/configured/archive-root")
must_fail(["ls", "/opt/farside/lib"], "/opt/farside/lib")
must_fail(["ls", "/opt/farside/var"], "/opt/farside/var")
must_fail(["ls", "/configured/archive-root"], "/configured/archive-root")

# sibling seating is not mounted
sib = exec_watch(["ls", "/opt/farside/watches"], timeout=15)
listing = sib.stdout or ""
if "W-SMOKEB" in listing or "seat B" in listing:
    sys.exit(f"sibling seating visible: {listing}")
print("ok  no sibling watches", listing.replace("\n", " ")[:120])

who = exec_watch(["bash", "-lc", "id; echo HOME=$HOME USER=$USER; pwd"], timeout=15)
print("ok  watch identity", (who.stdout or "").replace("\n", " | ")[:200])
if "contributor" in (who.stdout or "").lower():
    sys.exit("watch env leaked host username")

agent = exec_watch(["agent", "--version"], timeout=30)
if agent.returncode != 0:
    sys.exit(f"agent --version failed: {agent.stderr or agent.stdout}")
print("ok  agent", (agent.stdout or agent.stderr or "").splitlines()[:1])
mcp = exec_watch(
    ["agent", "--plugin-dir", "/opt/farside/empty-plugins", "--workspace", "/opt/farside/watches", "mcp", "list"],
    timeout=30,
)
blob = ((mcp.stdout or "") + "\n" + (mcp.stderr or "")).lower()
print("ok  mcp list", (mcp.stdout or mcp.stderr or "").splitlines()[:3])
if any(n in blob for n in ("gmail", "google-drive", "google-calendar", "plugin-gmail")):
    sys.exit(f"mcp list leaked account plugins: {(mcp.stdout or mcp.stderr)[:500]}")
plug = exec_watch(["ls", "/home/watch/.cursor/plugins"], timeout=10)
if plug.returncode == 0 and (plug.stdout or "").strip():
    sys.exit(f"watch can list plugins: {plug.stdout}")
print("ok  plugins dir not listable")

from biosim_operator.containment import exec_console
plant = exec_console(
    [
        "/opt/farside/bin/plant-watch",
        "--watch-id",
        "W-SMOKEA",
        "--mode",
        "advanced",
        "--url",
        INSIDE_PLANT_URL,
        "--prefix",
        "/opt/farside",
    ],
    user="eclss",
    stdin=b'{"sim_id": 0}\n',
    timeout=15,
)
if plant.returncode != 0:
    sys.exit(f"plant-watch failed: {plant.stderr or plant.stdout}")
read = exec_watch(["cat", "/opt/farside/var/W-SMOKEA/launch.json"], timeout=15)
if read.returncode == 0:
    sys.exit(f"watch read launch.json: {read.stdout}")
print("ok  watch cannot read var/launch.json")

# harvest then drop A; B is a second seat
harvest_dir = root_watches / "_harvest_smoke"
harvest_dir.mkdir(parents=True, exist_ok=True)
harvest_seat("W-SMOKEA", harvest_dir)
if not any(harvest_dir.rglob("*")):
    sys.exit(f"harvest empty at {harvest_dir}")
print("ok  harvest", harvest_dir)
stop_seat("W-SMOKEA")

start_seat("W-SMOKEB", b)
soul = exec_watch(["cat", "/opt/farside/watches/SOUL.md"], timeout=15)
if "seat B" not in (soul.stdout or ""):
    sys.exit(f"seat B did not see its SOUL: {soul.stdout} {soul.stderr}")
if "seat A" in (soul.stdout or ""):
    sys.exit("seat B saw seat A")
print("ok  second seat isolated")
stop_seat("W-SMOKEB")
print(json.dumps({"ok": True, "plant": HOST_PLANT_URL, "seats": True}))
PY
