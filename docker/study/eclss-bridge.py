#!/usr/bin/env python3
"""Stdio MCP shim. Talks only to the trusted eclss-broker over TCP.

Runs inside the operator container. No plant URL, no host FS.
"""
from __future__ import annotations

import json
import os
import socket
import sys

BROKER = os.environ.get("ECLSS_BROKER", "eclss-broker:9377")


def _rpc(payload: dict) -> dict:
    host, port_s = BROKER.rsplit(":", 1)
    port = int(port_s)
    blob = (json.dumps(payload) + "\n").encode()
    with socket.create_connection((host, port), timeout=30) as sock:
        sock.sendall(blob)
        chunks = []
        while True:
            data = sock.recv(65536)
            if not data:
                break
            chunks.append(data)
            if b"\n" in data:
                break
    return json.loads(b"".join(chunks).decode())


def main() -> int:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        msg = json.loads(raw)
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "eclss-bridge", "version": "1"},
            }
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            listed = _rpc({"op": "list"})
            result = {"tools": listed.get("tools") or []}
        elif method == "tools/call":
            params = msg.get("params") or {}
            result = _rpc(
                {
                    "op": "call",
                    "name": params.get("name"),
                    "arguments": params.get("arguments") or {},
                }
            )
        else:
            result = {"error": f"unsupported {method}"}
        if mid is not None:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
