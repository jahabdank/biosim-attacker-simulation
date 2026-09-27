#!/usr/bin/env python3
"""Per-episode inference relay to one fixed local model route."""

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
from archive_gate import port as _archive_port, credential as _archive_credential
require_enabled()

import http.client
import json
import os
import socketserver
import threading
import time
import uuid
from email.utils import parsedate_to_datetime
from sonnet_pacing import reserve_start, validate_spacing
from http.server import BaseHTTPRequestHandler
from pathlib import Path

MODEL = os.environ["STUDY_ROUTE_MODEL"]
SOCKET = os.environ["STUDY_ROUTE_SOCKET"]
ROUTES = {"gpt-5.6-luna": _archive_port('gateway_port_014'), "claude-sonnet-5": _archive_port('gateway_port_015')}
PORT = ROUTES[MODEL]
HOSTS = {
    'gpt-5.6-luna': _archive_setting('gateway_host_014'),
    'claude-sonnet-5': _archive_setting('gateway_host_015'),
}
HOST = HOSTS[MODEL]
SPACING = validate_spacing(os.environ.get("STUDY_SONNET_MIN_SPACING_S", "65"))
REQUEST_LOCK = threading.Lock()
FAILED = False
LOG_LOCK = threading.Lock()


def diagnostic(event: dict) -> None:
    path = os.environ.get("STUDY_ROUTE_DIAGNOSTICS")
    if path:
        with LOG_LOCK, Path(path).open("a") as stream:
            stream.write(json.dumps(event) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


def record_usage(payload: bytes, request_id: str) -> None:
    try:
        usage = json.loads(payload).get("usage")
    except (ValueError, AttributeError):
        return
    if not isinstance(usage, dict):
        return
    def numeric_fields(value):
        if not isinstance(value, dict):
            return {}
        return {k: (numeric_fields(v) if isinstance(v, dict) else v)
                for k, v in value.items() if k in {
                    "prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens",
                    "cached_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
                    "prompt_tokens_details", "completion_tokens_details", "reasoning_tokens"}
                and (isinstance(v, dict) or type(v) in (int, float))}
    diagnostic({"event": "usage", "request_id": request_id, "usage": numeric_fields(usage)})


def record_stream_error(payload: bytes, request_id: str, *, event_error: bool = False) -> bool:
    global FAILED
    try:
        data = json.loads(payload)
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    error = data.get("error")
    if not event_error and not error and data.get("type") != "error":
        return False
    fields = error if isinstance(error, dict) else data
    codes = [fields.get(k) for k in ("code", "type", "status", "status_code")]
    quota = any(str(code).lower() in {"429", "rate_limit_error", "rate_limit_exceeded",
                "too_many_requests", "quota_exceeded", "resource_exhausted"} for code in codes)
    FAILED = True
    diagnostic({"event": "stream_error", "request_id": request_id, "at": time.time(),
                "status": 429 if quota else 502, "quota_failure": quota})
    return True


class SSEInspector:
    def __init__(self, request_id: str):
        self.request_id = request_id
        self.pending = b""
        self.data = []
        self.event_error = False

    def dispatch(self) -> bool:
        payload = b"\n".join(self.data)
        failed = record_stream_error(payload, self.request_id, event_error=self.event_error)
        if not failed:
            record_usage(payload, self.request_id)
        self.data = []
        self.event_error = False
        return failed

    def feed(self, chunk: bytes, *, final: bool = False) -> bool:
        self.pending += chunk
        if len(self.pending) + sum(map(len, self.data)) > 2_000_000:
            return record_stream_error(b"", self.request_id, event_error=True)
        lines = self.pending.split(b"\n")
        self.pending = lines.pop()
        if final and self.pending:
            lines.append(self.pending)
            self.pending = b""
        for raw in lines:
            line = raw.rstrip(b"\r")
            if not line:
                if self.dispatch():
                    return True
            elif line.startswith(b"event:"):
                self.event_error = line[6:].strip() == b"error"
            elif line.startswith(b"data:"):
                self.data.append(line[5:].lstrip())
        return self.dispatch() if final and (self.data or self.event_error) else False


def retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, validate_spacing(value))
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
        except (ValueError, TypeError, OverflowError):
            return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        global FAILED
        # A failed route is latched for this episode; client retries cannot reach upstream.
        with REQUEST_LOCK:
            if FAILED:
                self.send_error(503, "episode route stopped after upstream failure")
                return
            self._post()

    def _post(self):
        global FAILED
        request_id = uuid.uuid4().hex
        if self.path != "/v1/chat/completions":
            self.send_error(403)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 16_000_000:
                self.send_error(413)
                return
            body = json.loads(self.rfile.read(size))
            if body.get("model") != MODEL:
                self.send_error(403, "model route mismatch")
                return
            headers = {"Content-Type": "application/json"}
            if MODEL == "gpt-5.6-luna":
                headers["api-key"] = os.environ["ROUTE_A_HARNESS_API_KEY"]
            else:
                headers["Authorization"] = "Bearer " + _archive_credential('credential_file_002')
            wait = 0.0
            paced = MODEL == "claude-sonnet-5" and os.environ.get("STUDY_SONNET_PACING") == "1"
            requested = time.time()
            if paced:
                before = time.monotonic()
                reserve_start(Path("/run/biosim-sonnet-pacing.json"), SPACING)
                wait = time.monotonic() - before
            diagnostic({"event": "admitted", "request_id": request_id, "model": MODEL,
                        "requested": requested, "started": time.time(), "wait_s": wait,
                        "minimum_spacing_s": SPACING if paced else None})
            conn = http.client.HTTPConnection(HOST, PORT, timeout=480)
            try:
                conn.request("POST", self.path, json.dumps(body).encode(), headers)
                reply = conn.getresponse()
                FAILED = reply.status >= 400
                metadata = {}
                for name in ("x-ratelimit-limit-requests", "x-ratelimit-remaining-requests",
                             "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens"):
                    value = reply.getheader(name)
                    if value and value.isdecimal():
                        metadata[name] = int(value)
                retry_after = retry_after_seconds(reply.getheader("Retry-After"))
                diagnostic({"event": "response", "request_id": request_id, "at": time.time(),
                            "status": reply.status, "retry_after_s": retry_after,
                            "rate_limit": metadata})
                self.send_response(reply.status)
                self.send_header("Content-Type", reply.getheader("Content-Type", "application/json"))
                length = reply.getheader("Content-Length")
                if length:
                    self.send_header("Content-Length", length)
                else:
                    self.send_header("Connection", "close")
                    self.close_connection = True
                self.end_headers()
                pending = b""
                streaming = "text/event-stream" in reply.getheader("Content-Type", "")
                inspector = SSEInspector(request_id)
                while True:
                    chunk = reply.read1(65536)
                    if not chunk:
                        break
                    if streaming:
                        if inspector.feed(chunk):
                            self.close_connection = True
                            return
                    else:
                        pending += chunk
                        if len(pending) > 2_000_000:
                            pending = b""
                    self.wfile.write(chunk)
                    self.wfile.flush()
                if streaming:
                    if inspector.feed(b"", final=True):
                        self.close_connection = True
                else:
                    record_stream_error(pending, request_id)
                    record_usage(pending, request_id)
            finally:
                conn.close()
        except (ValueError, KeyError, OSError, http.client.HTTPException):
            FAILED = True
            diagnostic({"event": "transport_error", "request_id": request_id, "at": time.time()})
            self.close_connection = True

    def do_GET(self):
        self.send_error(405)


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


if __name__ == "__main__":
    path = Path(SOCKET)
    path.parent.mkdir(parents=True, exist_ok=True)
    with Server(str(path), Handler) as server:
        path.chmod(0o666)
        server.serve_forever()
