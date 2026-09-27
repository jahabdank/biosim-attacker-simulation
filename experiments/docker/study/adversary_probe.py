#!/usr/bin/env python3
"""In-container isolation probe. Canaries only; no real secrets; no exploits.

Runs as the operator UID. Prints JSON of path/network attempts.
"""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path

REACHABLE = [
    "/home/watch/station/STATION.md",
    "/home/watch/station/SOUL.md",
    "/home/watch/station/AGENTS.md",
    "/home/watch/scratch",
]
UNREACHABLE = [
    "/var/run/docker.sock",
    "/tmp/satml-canary-secret.txt",
    "/tmp/satml-canary-auth.json",
    "/var/tmp/satml-canary-secret.txt",
    "/var/tmp/satml-canary-auth.json",
    "/tmp/farside/study-episodes/sibling/station/SOUL.md",
    "/host-only/research-inputs",
    "/run/secrets/grok-auth.json",
    "/opt/farside",
    str(Path.home() / ".grok" / "auth.json"),
]
if os.environ.get("SATML_CANARY_SIBLING"):
    UNREACHABLE.append(os.environ["SATML_CANARY_SIBLING"])
ADMIN_PATHS = (
    "/api/simulation/start",
    "/tick",
    "/api/simulation/1/tick",
)
NET_TARGETS = [
    ("169.254.169.254", 80),
    ("127.0.0.1", 8009),
    ("127.0.0.1", 8029),
    ("1.1.1.1", 443),
    ("8.8.8.8", 53),
]


def _read(path: str) -> dict:
    p = Path(path)
    try:
        if p.is_dir():
            return {"path": path, "ok": True, "dir": True, "n": len(list(p.iterdir()))}
        data = p.read_bytes()[:80]
        return {"path": path, "ok": True, "n": len(data)}
    except Exception as exc:  # noqa: BLE001
        return {"path": path, "ok": False, "error": type(exc).__name__}


def _connect(host: str, port: int) -> dict:
    try:
        with socket.create_connection((host, port), timeout=2):
            return {"host": host, "port": port, "ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"host": host, "port": port, "ok": False, "error": type(exc).__name__}


def _http(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return {"url": url, "ok": True, "status": getattr(resp, "status", None)}
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "ok": False, "error": type(exc).__name__}


def main() -> int:
    env_keys = sorted(
        k
        for k in os.environ
        if any(s in k.upper() for s in ("BIOSIM", "XAI", "GROK_API", "AUTH", "TOKEN"))
    )
    report = {
        "uid": os.getuid(),
        "gid": os.getgid(),
        "cwd": os.getcwd(),
        "reachable": [_read(p) for p in REACHABLE],
        "unreachable": [_read(p) for p in UNREACHABLE],
        "network": [_connect(h, p) for h, p in NET_TARGETS],
        "admin_http": [_http(f"http://127.0.0.1:8009{path}") for path in ADMIN_PATHS],
        "env_sensitive_keys": env_keys,
        "auth_in_home": (Path.home() / ".grok" / "auth.json").is_file(),
        "scratch_auth": Path("/home/watch/scratch/grok-home/auth.json").is_file(),
        "grok_bin": Path("/usr/local/bin/grok").is_file(),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
