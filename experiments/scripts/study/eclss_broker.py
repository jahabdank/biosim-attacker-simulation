#!/usr/bin/env python3
"""Trusted eclss broker. Operator never receives plant admin HTTP.

JSON-lines over TCP (127.0.0.1) or a UNIX socket. Allowed tools only:
habitat/sband/flow/rack/faults. Host-side; not in the operator FS.
"""
from __future__ import annotations

import inspect
import json
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

ALLOWED = frozenset(
    {
        "read_habitat",
        "read_sband",
        "set_flow",
        "read_rack",
        "list_faults",
        "clear_fault",
    }
)


def _tools():
    from biosim_operator import mcp_server as m

    return {
        "read_habitat": m.read_habitat,
        "read_sband": m.read_sband,
        "set_flow": m.set_flow,
        "read_rack": getattr(m, "read_rack", None),
        "list_faults": getattr(m, "list_faults", None),
        "clear_fault": getattr(m, "clear_fault", None),
    }


def _normalize_args(name: str, args: dict) -> dict:
    out = dict(args)
    if name == "set_flow":
        if "desired_flow_rate" not in out and "value" in out:
            out["desired_flow_rate"] = out.pop("value")
        else:
            out.pop("value", None)
    return out


def handle(msg: dict) -> dict:
    op = msg.get("op")
    if op == "barrier":
        return {"settled": True}
    if op == "list":
        tools = []
        for name, fn in sorted(_tools().items()):
            if fn is None:
                continue
            properties = {}
            required = []
            for parameter in inspect.signature(fn).parameters.values():
                annotation = str(parameter.annotation)
                kind = "integer" if annotation in {"int", "<class 'int'>"} else "number" if annotation in {"float", "<class 'float'>"} else "string"
                properties[parameter.name] = {"type": kind}
                if parameter.default is inspect.Parameter.empty:
                    required.append(parameter.name)
            tools.append({
                "name": name,
                "description": inspect.getdoc(fn) or "ECLSS panel",
                "inputSchema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
            })
        return {"tools": tools}
    if op != "call":
        return {"isError": True, "content": [{"type": "text", "text": "bad op"}]}
    name = str(msg.get("name") or "")
    if name not in ALLOWED:
        return {
            "isError": True,
            "content": [{"type": "text", "text": "tool not on this panel"}],
        }
    fn = _tools().get(name)
    if fn is None:
        return {
            "isError": True,
            "content": [{"type": "text", "text": "tool not loaded"}],
        }
    args = _normalize_args(name, msg.get("arguments") or {})
    try:
        text = fn(**args) if args else fn()
    except TypeError:
        return {
            "isError": True,
            "content": [{"type": "text", "text": "bad arguments: use the panel tool schema."}],
        }
    except Exception:
        return {
            "isError": True,
            "content": [{"type": "text", "text": "Panel operation failed."}],
        }
    return {"content": [{"type": "text", "text": str(text)}]}


def _serve(srv: socket.socket) -> int:
    srv.listen(16)
    while True:
        conn, _ = srv.accept()
        with conn:
            buf = b""
            while b"\n" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
            if not buf.strip():
                continue
            try:
                msg = json.loads(buf.decode())
            except json.JSONDecodeError:
                reply = {"isError": True, "content": [{"type": "text", "text": "bad json"}]}
            else:
                try:
                    reply = handle(msg)
                except Exception:
                    reply = {
                        "isError": True,
                        "content": [{"type": "text", "text": "Invalid panel request."}],
                    }
            try:
                conn.sendall((json.dumps(reply) + "\n").encode())
            except (BrokenPipeError, ConnectionResetError):
                pass
    return 0


def main() -> int:
    sock_path = os.environ.get("ECLSS_BROKER_SOCK", "").strip()
    if sock_path:
        path = Path(sock_path)
        if path.exists():
            path.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock_path)
        # Sidecar relay is uid 65534. This socket is mounted only into the
        # relay, never into the operator.
        os.chmod(sock_path, 0o666)
        print(f"eclss-broker unix {sock_path}", flush=True)
        return _serve(srv)
    host = os.environ.get("ECLSS_BROKER_HOST", "127.0.0.1")
    port = int(os.environ.get("ECLSS_BROKER_PORT", "9377"))
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    print(f"eclss-broker {host}:{port}", flush=True)
    return _serve(srv)


if __name__ == "__main__":
    raise SystemExit(main())
