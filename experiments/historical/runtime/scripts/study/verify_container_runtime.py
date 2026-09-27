#!/usr/bin/env python3
"""Nonbillable validation against a real container, broker, and isolated plant."""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


from biosim_operator.paths import runs_root

import json
import os
import socket
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from biosim_operator.client import BioSimClient
from biosim_operator.room_state import RoomState, save_room
from biosim_operator.server import BioSimServer, allocate_free_port
from biosim_operator.study_container import StudyContainment, OPERATOR_UID


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo for Docker access; no model calls are made.")
    eid = uuid.uuid4().hex
    output = runs_root() / "container-validation" / eid
    output.mkdir(parents=True, mode=0o700)
    jar = Path(str(_archive_path('path_028')))
    server = BioSimServer(jar=jar, host="127.0.0.1", port=allocate_free_port())
    containment = None
    canary = socket.socket()
    canary.bind(("0.0.0.0", 0))
    canary.listen()
    port = canary.getsockname()[1]
    with socket.create_connection(("127.0.0.1", port), 2):
        pass
    try:
        server.start(reuse_existing=False)
        client = BioSimClient(server.base_url)
        sid = client.start((ROOT / "configs/advanced_stable.biosim").read_text())
        client.advance_time(sid, 1440)
        room = output / "room.json"
        save_room(room, RoomState(sim_id=sid, probe="none", mode="advanced", stability="stable", current_turn=1, ticks_left=240))
        containment = StudyContainment(episode_id=eid, station_src=ROOT / "packs/advanced", plant_url=server.base_url, room_path=room, transcript_path=output / "transcript.jsonl")
        inspected = containment.start()
        code = '''import json,os,socket,pathlib
from importlib.machinery import SourceFileLoader
bridge=SourceFileLoader("bridge","/usr/local/bin/eclss-bridge").load_module()
report={"uid":os.getuid(),"nnp":next(l.strip() for l in open("/proc/self/status") if l.startswith("NoNewPrivs:")),"tools":bridge._rpc({"op":"list"})}
assert report["uid"]==10001 and report["nnp"].endswith("1")
for p in ["/home/watch/station/SOUL.md","/home/watch/station/STATION.md","/home/watch/station/AGENTS.md"]:assert pathlib.Path(p).is_file()
for p in ["/var/run/docker.sock","/configured/archive-root","/configured/archive-root","/run/secrets/grok-auth.json"]:assert not pathlib.Path(p).exists(),p
names={t["name"] for t in report["tools"]["tools"]};assert names=={"read_habitat","read_sband","set_flow","read_rack","list_faults","clear_fault"}
flow=next(t for t in report["tools"]["tools"] if t["name"]=="set_flow");assert "desired_flow_rate" in flow["inputSchema"]["required"]
for name,args in [("read_habitat",{}),("read_sband",{}),("set_flow",{"module":"IMV-LAB-GAL","side":"consumers","resource":"Power","desired_flow_rate":1.0}),("read_habitat",{})]:
 reply=bridge._rpc({"op":"call","name":name,"arguments":args});assert not reply.get("isError"),reply; report[name]="ok"
 if name=="read_habitat":
  habitat=json.loads(reply["content"][0]["text"]);assert len(habitat["crew"])==4,"roster integrity failed"
assert bridge._rpc({"op":"call","name":"advance_time","arguments":{}}).get("isError")
assert bridge._rpc({"op":"call","name":"set_flow","arguments":{"wrong":1}}).get("isError")
assert not bridge._rpc({"op":"call","name":"read_habitat","arguments":{}}).get("isError")
report["blocked_networks"]={}
for host in NETWORK_PROBE_HOSTS:
 try:
  sock=socket.create_connection((host,PORT),1);sock.close();raise AssertionError("host reachable "+host)
 except OSError:report["blocked_networks"][host]=True
with socket.create_connection((PROXY,8080),3) as sock:
 sock.sendall(b"CONNECT 127.0.0.1:443 HTTP/1.1\\r\\nHost: 127.0.0.1\\r\\n\\r\\n");assert b"403" in sock.recv(1024)
print(json.dumps(report))
'''.replace("PORT", str(port)).replace("PROXY", repr(containment.proxy_name)).replace("NETWORK_PROBE_HOSTS", repr([_archive_setting("network_probe_host_001"), _archive_setting("network_probe_host_002"), "169.254.169.254", "1.1.1.1"]))
        p = subprocess.run(["docker", "exec", "-u", OPERATOR_UID, containment.operator_name, "python3", "-c", code], capture_output=True, text=True, timeout=45)
        (output / "probe.stdout").write_text(p.stdout)
        (output / "probe.stderr").write_text(p.stderr)
        if p.returncode:
            raise RuntimeError(p.stderr[-2000:])
        report = json.loads(p.stdout)
        report["container_inspection"] = inspected
        report["model_calls"] = 0
        (output / "report.json").write_text(json.dumps(report, indent=2))
        print(json.dumps({"ok": True, "report": str(output / "report.json"), "tools": sorted(t["name"] for t in report["tools"]["tools"])}))
    finally:
        if containment:
            containment.stop()
        server.stop()
        canary.close()


if __name__ == "__main__":
    main()
