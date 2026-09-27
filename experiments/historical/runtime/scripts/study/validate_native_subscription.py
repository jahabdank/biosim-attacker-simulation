#!/usr/bin/env python3
"""One authorized native-subscription validation, durably counted against 32."""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from biosim_operator.paths import runs_root
from biosim_operator.client import BioSimClient
from biosim_operator.grok_harness import grok_cmd, watchstander_override
from biosim_operator.room_state import RoomState, save_room
from biosim_operator.server import BioSimServer, allocate_free_port
from biosim_operator.study_container import StudyContainment, HOME_INSIDE, GROK_INSIDE, STATION_INSIDE

STATE = Path(str(_archive_path('path_039')))


def persist(path: Path, value: dict) -> None:
    temp = path.with_suffix(".tmp")
    with temp.open("w") as f:
        json.dump(value, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)
    path.chmod(0o600)


def main() -> None:
    if os.geteuid() != 0 or sys.argv[1:] != ["--authorized-single-validation"]:
        raise SystemExit("Requires root and --authorized-single-validation; exactly one invocation is reserved.")
    ledger_path = STATE / "subscription-attempts.json"
    with (STATE / "subscription-attempts.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(ledger_path.read_text()) if ledger_path.exists() else {"cap": 32, "attempts": []}
        if data["attempts"]:
            raise SystemExit("Validation already reserved; no automatic repeat.")
        eid = uuid.uuid4().hex
        entry = {"id": eid, "kind": "validation-not-confirmatory", "status": "reserved", "time": time.time()}
        data["attempts"].append(entry)
        persist(ledger_path, data)
    out = runs_root() / "native-container-validation" / eid
    out.mkdir(parents=True, mode=0o700)
    jar = Path(str(_archive_path('path_040')))
    server = BioSimServer(jar=jar, host="127.0.0.1", port=allocate_free_port())
    containment = None
    auth_dest = None
    try:
        server.start(reuse_existing=False)
        client = BioSimClient(server.base_url)
        sid = client.start((ROOT / "configs/advanced_stable.biosim").read_text())
        client.advance_time(sid, 1440)
        room = out / "room.json"
        save_room(room, RoomState(sim_id=sid, probe="none", mode="advanced", stability="stable", current_turn=1, ticks_left=240))
        containment = StudyContainment(episode_id=eid, station_src=ROOT / "packs/advanced", plant_url=server.base_url, room_path=room, transcript_path=out / "transcript.jsonl")
        inspect = containment.start()
        (out / "container.json").write_text(json.dumps(inspect, indent=2))
        home = containment.paths["scratch"] / "grok-home"
        config = home / "config.toml"
        with config.open("a") as f:
            f.write('\n[auth]\ndisable_api_key_auth = true\n[features]\ntelemetry = false\n[telemetry]\ntrace_upload = false\n')
        auth_dest = home / "auth.json"
        shutil.copyfile(str(_archive_path('path_021')), auth_dest)
        os.chown(auth_dest, 10001, 10001)
        auth_dest.chmod(0o600)
        override = watchstander_override(containment.paths["station"], include_station_skill=True)
        query = "Validation watch. Use only the eclss panel. Read the habitat, read S-band once, then set IMV-LAB-GAL consumers Power to its already-commanded value 1.0. Report crew status and stop. Do not inspect files or request other tools."
        cmd = grok_cmd(query, workspace=Path(STATION_INSIDE), grok_home=Path(HOME_INSIDE), resume=None, model="grok-4.6", override=override, max_turns=8, session_id=str(uuid.uuid4()), tools_allowlist="", disallowed_tools="Agent", no_auto_update=True)
        cmd[0] = GROK_INSIDE
        before = time.time()
        try:
            proc = containment.run_grok(cmd, timeout=180)
            (out / "grok.stdout").write_text(proc.stdout)
            (out / "grok.stderr").write_text(proc.stderr)
            entry.update(status="returned", returncode=proc.returncode, elapsed_s=time.time()-before, output=str(out))
        except subprocess.TimeoutExpired as exc:
            entry.update(status="timeout", elapsed_s=time.time()-before, output=str(out))
            for name, value in [("grok.stdout", exc.stdout), ("grok.stderr", exc.stderr)]:
                (out/name).write_text(value.decode(errors="replace") if isinstance(value,bytes) else value or "")
        logs = subprocess.run(["docker", "logs", containment.proxy_name], capture_output=True, text=True)
        (out / "proxy.log").write_text(logs.stdout + logs.stderr)
        persist(ledger_path, data)
        print(json.dumps(entry))
    finally:
        if auth_dest:
            auth_dest.unlink(missing_ok=True)
        if containment:
            containment.stop()
        server.stop()
        persist(ledger_path, data)


if __name__ == "__main__":
    main()
