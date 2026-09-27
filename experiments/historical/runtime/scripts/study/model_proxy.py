#!/usr/bin/env python3
"""Trusted model proxy. Holds subscription credentials off the operator FS.

Never returns auth.json. Default refuses paid forward unless
STUDY_MODEL_PROXY_FORWARD=1 (parent-gated). Allowlisted upstream only.
"""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

AUTH = Path(os.environ.get("STUDY_GROK_AUTH_PATH") or (_archive_path('path_038')))
ALLOWED_UPSTREAM = tuple(
    h
    for h in os.environ.get(
        "STUDY_MODEL_UPSTREAM_HOSTS",
        "api.x.ai,accounts.x.ai",
    ).split(",")
    if h.strip()
)


def _auth_present() -> bool:
    return AUTH.is_file()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("model-proxy " + (fmt % args) + "\n")

    def _deny(self, code: int, msg: str) -> None:
        body = json.dumps({"error": msg}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/health", "/"}:
            # Do not report whether auth exists to the operator.
            self._deny(200, "ok")
            return
        if "auth" in self.path or "token" in self.path:
            self._deny(404, "not found")
            return
        if self.path.startswith("/v1/models"):
            # Non-billable routing surface. No inference. No secrets.
            body = json.dumps({"data": [{"id": "grok-4.6", "object": "model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._deny(403, "operator may not fetch this")

    def do_POST(self) -> None:  # noqa: N802
        if os.environ.get("STUDY_MODEL_PROXY_FORWARD") != "1":
            self._deny(403, "paid forward gated")
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > 2_000_000:
            self._deny(413, "too large")
            return
        _ = self.rfile.read(length) if length else b""
        upstream = os.environ.get("STUDY_MODEL_UPSTREAM", "https://api.x.ai")
        host = urlparse(upstream).hostname or ""
        if host not in ALLOWED_UPSTREAM:
            self._deny(403, "upstream not allowlisted")
            return
        self._deny(501, "forward not implemented in this preflight")


def main() -> int:
    if _auth_present():
        mode = oct(AUTH.stat().st_mode & 0o777)
        print(f"model-proxy auth.json present mode={mode}", flush=True)
    else:
        print("model-proxy auth.json absent", flush=True)
    host = os.environ.get("MODEL_PROXY_HOST", "127.0.0.1")
    port = int(os.environ.get("MODEL_PROXY_PORT", "8080"))
    ThreadingHTTPServer((host, port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
