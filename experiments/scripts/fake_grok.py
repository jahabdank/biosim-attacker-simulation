#!/usr/bin/env python3
"""Deterministic, non-inference CLI stand-in for the actual episode driver."""
from __future__ import annotations
import json
import os
from pathlib import Path
import socket
import sys
import time
import tempfile
import tomllib


def argument(name, default=""):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    with tempfile.TemporaryFile(dir="/tmp") as scratch:
        scratch.write(b"temporary-storage-check")
        scratch.seek(0)
        assert scratch.read() == b"temporary-storage-check"
    home = Path(os.environ["GROK_HOME"])
    config = tomllib.loads((home / "config.toml").read_text())
    entry = config["mcp_servers"]["eclss"]
    env = entry.get("env", {})
    session = argument("--resume") or argument("--session-id")
    if not session:
        raise ValueError("episode must supply a persistent session id")
    state_path = home / "sessions" / session / "fake-state.json"
    old = json.loads(state_path.read_text()) if state_path.exists() else {"watches": []}
    if old["watches"] and not argument("--resume"):
        raise ValueError("session continuity was lost")
    watch = len(old["watches"]) + 1
    if watch == int(os.environ.get("FAKE_HANG_WATCH", "0")):
        time.sleep(3600)
    prompt = argument("--system-prompt-override")
    if not all(piece in prompt for piece in ("ECLSS", "read_habitat", "read_sband")):
        raise ValueError("assembled prompt is incomplete")
    broker = env.get("ECLSS_BROKER")
    if broker:
        def call(name, args):
            host, port = broker.rsplit(":", 1)
            with socket.create_connection((host, int(port)), timeout=30) as sock:
                sock.sendall((json.dumps({"op": "call", "name": name, "arguments": args}) + "\n").encode())
                with sock.makefile("rb") as stream:
                    result = json.loads(stream.readline())
            if result.get("isError"):
                raise RuntimeError("panel call failed")
            return result["content"][0]["text"]
    else:
        os.environ.update({str(k): str(v) for k, v in env.items()})
        sys.path.insert(0, env["PYTHONPATH"])
        from biosim_operator import mcp_server
        def call(name, args):
            return getattr(mcp_server, name)(**args)
    board = call("read_habitat", {})
    frame = call("read_sband", {})
    duplicate = None
    if "twice consecutively" in prompt:
        duplicate = call("read_sband", {})
        if duplicate != frame:
            raise ValueError("cached frame changed")
    flow = call("set_flow", {"module": "IMV-LAB-GAL", "side": "consumers", "resource": "Power", "desired_flow_rate": 1.0})
    old["watches"].append({"watch": watch, "query": argument("-p"), "duplicate_match": duplicate == frame,
                            "resumed": bool(argument("--resume"))})
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(old))
    (state_path.parent / "signals.json").write_text(json.dumps({"compactionCount": 0, "turnCount": watch,
                                                               "contextWindowTokens": 500000,
                                                               "primaryModelId": argument("-m")}))
    print(json.dumps({"type": "result", "result": "Board read; receipt checked; ventilation set.",
                      "session_id": session, "fake_watch": watch, "history_length": len(old["watches"]),
                      "tmp_write_ok": True, "cached_match": duplicate == frame, "sband": json.loads(frame), "flow": json.loads(flow)}), flush=True)
    if watch == int(os.environ.get("FAKE_FAILURE_WATCH", "0")):
        print("Error: synthetic operator failure", file=sys.stderr)
        return 2
    if watch == int(os.environ.get("FAKE_CAP_WATCH", "0")):
        print("Error: max turns reached", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
