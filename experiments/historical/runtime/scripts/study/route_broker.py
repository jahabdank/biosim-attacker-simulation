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
ROUTES = {
    "claude-opus-5": {"port": _archive_port('gateway_port_001'), "upstream_model": "claude-opus-5", "path": "/v1/chat/completions", "host": _archive_setting('gateway_host_001')},
    "gpt-5.6-sol": {"port": _archive_port('gateway_port_002'), "upstream_model": "gpt-5.6-sol", "path": "/v1/chat/completions", "host": _archive_setting('gateway_host_002')},
    "claude-haiku-4-5": {"port": _archive_port('gateway_port_003'), "upstream_model": "claude-haiku-4-5", "path": "/v1/chat/completions", "host": _archive_setting('gateway_host_003')},
    "gpt-5.6-terra": {"port": _archive_port('gateway_port_004'), "upstream_model": "gpt-5.6-terra", "path": "/v1/chat/completions", "host": _archive_setting('gateway_host_004')},
    "gpt-5.6-luna": {"port": _archive_port('gateway_port_005'), "upstream_model": "gpt-5.6-luna", "path": "/v1/chat/completions", "host": _archive_setting('gateway_host_005')},
    "gpt-6-luna": {"port": _archive_port('gateway_port_006'), "upstream_model": "gpt-6-luna", "path": "/v1/responses", "host": _archive_setting('gateway_host_006')},
    "gpt-6-sol": {"port": _archive_port('gateway_port_007'), "upstream_model": "gpt-6-sol", "path": "/v1/responses", "host": _archive_setting('gateway_host_007')},
    "gpt-6-astra": {"port": _archive_port('gateway_port_008'), "upstream_model": "gpt-6-astra", "path": "/v1/responses", "host": _archive_setting('gateway_host_008')},
    "grok-4.6-route-a": {"port": _archive_port('gateway_port_009'), "upstream_model": "grok-4-6", "path": "/v1/chat/completions", "host": _archive_setting('gateway_host_009')},
    "claude-sonnet-5": {"port": _archive_port('gateway_port_010'), "upstream_model": "claude-sonnet-5", "path": "/v1/chat/completions", "host": _archive_setting('gateway_host_010')},
    "grok-4.6-route-b": {"port": _archive_port('gateway_port_011'), "upstream_model": "grok-4.6", "path": "/v1/chat/completions", "host": _archive_setting('gateway_host_011')},
    "claude-sonnet-5-route-b": {"port": _archive_port('gateway_port_012'), "upstream_model": "claude-sonnet-5", "path": "/v1/chat/completions", "host": _archive_setting('gateway_host_012')},
    "claude-opus-5-route-b": {"port": _archive_port('gateway_port_013'), "upstream_model": "claude-opus-5", "path": "/v1/chat/completions", "host": _archive_setting('gateway_host_013')},
}
ROUTE = ROUTES[MODEL]
PORT = ROUTE["port"]
HOST = ROUTE["host"]
SPACING = validate_spacing(
    os.environ.get("STUDY_ROUTE_MIN_SPACING_S")
    or os.environ.get("STUDY_SONNET_MIN_SPACING_S", "65")
)
REQUEST_LOCK = threading.Lock()
FAILED = False
LOG_LOCK = threading.Lock()
TRANSIENT_STATUS = frozenset({500, 502, 503})
TRANSIENT_TRIES = max(1, int(os.environ.get("STUDY_ROUTE_TRANSIENT_TRIES", "3")))


def diagnostic(event: dict) -> None:
    path = os.environ.get("STUDY_ROUTE_DIAGNOSTICS")
    if path:
        with LOG_LOCK, Path(path).open("a") as stream:
            stream.write(json.dumps(event) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


def record_usage(payload: bytes | dict, request_id: str) -> None:
    try:
        data = payload if isinstance(payload, dict) else json.loads(payload)
        reported_model = data.get("model")
        usage = data.get("usage")
    except (ValueError, AttributeError):
        return
    if not isinstance(usage, dict):
        return
    if isinstance(reported_model, str) and reported_model:
        diagnostic({"event": "identity", "request_id": request_id,
                    "reported_model": reported_model})
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


def record_stream_error(payload: bytes | dict, request_id: str, *, event_error: bool = False) -> bool:
    global FAILED
    try:
        data = payload if isinstance(payload, dict) else json.loads(payload)
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


def ensure_choice_deltas(data):
    """Grok CLI requires choices[].delta; provider_a sometimes omits it."""
    if isinstance(data, dict) and isinstance(data.get("choices"), list):
        for choice in data["choices"]:
            if isinstance(choice, dict) and "delta" not in choice:
                choice["delta"] = {}
    return data


class SSEInspector:
    def __init__(self, request_id: str):
        self.request_id = request_id
        self.pending = b""
        self.data = []
        self.event_name = b""
        self.event_error = False
        self.out = bytearray()

    def take(self) -> bytes:
        out = bytes(self.out)
        self.out.clear()
        return out

    def dispatch(self) -> bool:
        payload = b"\n".join(self.data)
        if self.event_name:
            diagnostic({"event": "sse_event", "request_id": self.request_id,
                        "at": time.time(), "name": self.event_name.decode("ascii", "replace")})
        if self.data and payload.strip() != b"[DONE]" and not self.event_error:
            json.loads(payload)
        failed = record_stream_error(payload, self.request_id, event_error=self.event_error)
        if not failed:
            record_usage(payload, self.request_id)
            # provider_a may inject SSE heartbeats. They are transport metadata,
            # not Responses API events; Grok's typed parser rejects them.
            if self.event_name == b"keepalive":
                self.data = []
                self.event_name = b""
                self.event_error = False
                return False
            if self.event_name:
                self.out += b"event: " + self.event_name + b"\n"
            if payload.strip() == b"[DONE]":
                self.out += b"data: [DONE]\n\n"
            elif payload.strip() and not self.event_error:
                try:
                    data = ensure_choice_deltas(json.loads(payload))
                    self.out += b"data: " + json.dumps(data, separators=(",", ":")).encode() + b"\n\n"
                except ValueError:
                    self.out += b"data: " + payload + b"\n\n"
        self.data = []
        self.event_name = b""
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
                self.event_name = line[6:].strip()
                self.event_error = self.event_name == b"error"
            elif line.startswith(b"data:"):
                self.data.append(line[5:].lstrip())
        return self.dispatch() if final and (self.data or self.event_error) else False


def reject_json_constant(value: str) -> None:
    raise ValueError("Non-JSON numeric constant")


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
        if self.path != ROUTE["path"]:
            self.send_error(403)
            return
        phase = "request_parse"
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 16_000_000:
                self.send_error(413)
                return
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError("incomplete request body")
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError("request body must be an object")
            if body.get("model") != MODEL:
                self.send_error(403, "model route mismatch")
                return
            body["model"] = ROUTE["upstream_model"]
            if MODEL in {"claude-sonnet-5-route-b", "claude-opus-5-route-b"} and "max_tokens" in body:
                if "max_completion_tokens" in body:
                    self.send_error(400, "both max_tokens and max_completion_tokens supplied")
                    return
                body["max_completion_tokens"] = body.pop("max_tokens")
            phase = "admission"
            headers = {"Content-Type": "application/json"}
            if MODEL in {"gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-6-luna", "gpt-6-sol", "gpt-6-astra", "grok-4.6-route-a"}:
                headers["api-key"] = os.environ["ROUTE_A_HARNESS_API_KEY"]
            elif MODEL.startswith("provider_b-"):
                headers["Authorization"] = "Bearer episode-local-no-secret"
            else:
                headers["Authorization"] = "Bearer " + _archive_credential('credential_file_001')
            wait = 0.0
            paced = os.environ.get("STUDY_ROUTE_PACING") == "1" or (
                MODEL == "claude-sonnet-5" and os.environ.get("STUDY_SONNET_PACING") == "1"
            )
            requested = time.time()
            if paced:
                before = time.monotonic()
                reserve_start(Path('/run/biosim-sonnet-pacing.json') if MODEL.startswith('claude-') else Path('/run/biosim-' + MODEL + '-pacing.json'), SPACING)
                wait = time.monotonic() - before
            diagnostic({"event": "admitted", "request_id": request_id, "model": MODEL,
                        "requested": requested, "started": time.time(), "wait_s": wait,
                        "minimum_spacing_s": SPACING if paced else None})
            phase = "upstream_request"
            payload = json.dumps(body).encode()
            timeout = float(os.environ.get("STUDY_ROUTE_TIMEOUT_S", "1800"))
            attempt = 0
            conn = None
            reply = None
            while True:
                attempt += 1
                try:
                    conn = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
                    conn.request("POST", ROUTE["path"], payload, headers)
                    phase = "upstream_response"
                    reply = conn.getresponse()
                except (OSError, http.client.HTTPException):
                    if attempt < TRANSIENT_TRIES:
                        diagnostic({"event": "transient_retry", "request_id": request_id,
                                    "at": time.time(), "status": 502, "attempt": attempt,
                                    "tries": TRANSIENT_TRIES, "phase": phase})
                        time.sleep(min(2 ** attempt, 8))
                        phase = "upstream_request"
                        continue
                    raise
                metadata = {}
                for name in ("x-ratelimit-limit-requests", "x-ratelimit-remaining-requests",
                             "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens"):
                    value = reply.getheader(name)
                    if value and value.isdecimal():
                        metadata[name] = int(value)
                retry_after = retry_after_seconds(reply.getheader("Retry-After"))
                diagnostic({"event": "response", "request_id": request_id, "at": time.time(),
                            "status": reply.status, "retry_after_s": retry_after,
                            "rate_limit": metadata, "attempt": attempt})
                if reply.status in TRANSIENT_STATUS and attempt < TRANSIENT_TRIES:
                    try:
                        reply.read()
                    except (OSError, http.client.HTTPException):
                        pass
                    try:
                        conn.close()
                    except OSError:
                        pass
                    diagnostic({"event": "transient_retry", "request_id": request_id,
                                "at": time.time(), "status": reply.status,
                                "attempt": attempt, "tries": TRANSIENT_TRIES})
                    time.sleep(min(2 ** attempt, 8))
                    phase = "upstream_request"
                    continue
                break
            FAILED = reply.status >= 400
            phase = "client_response"
            try:
                self.send_response(reply.status)
                content_type = reply.getheader("Content-Type", "application/json")
                self.send_header("Content-Type", content_type)
                length = reply.getheader("Content-Length")
                streaming = "text/event-stream" in content_type
                if not streaming and length:
                    self.send_header("Content-Length", length)
                else:
                    # SSE is inspected and may be reserialized (choice delta fill,
                    # event-name preservation). Never forward the stale upstream
                    # byte length; close-delimit the transformed stream.
                    self.send_header("Connection", "close")
                    self.close_connection = True
                self.end_headers()
                pending = []
                inspector = SSEInspector(request_id)
                received = 0
                while True:
                    phase = "upstream_read"
                    chunk = reply.read1(65536)
                    if not chunk:
                        if length and received < int(length):
                            raise http.client.IncompleteRead(b"", int(length) - received)
                        break
                    received += len(chunk)
                    phase = "response_inspection"
                    if streaming:
                        failed = inspector.feed(chunk)
                        rewritten = inspector.take()
                        phase = "client_response"
                        if rewritten:
                            self.wfile.write(rewritten)
                            self.wfile.flush()
                        if failed:
                            self.close_connection = True
                            return
                    else:
                        pending.append(chunk)
                        phase = "client_response"
                        self.wfile.write(chunk)
                        self.wfile.flush()
                phase = "response_inspection"
                if streaming:
                    failed = inspector.feed(b"", final=True)
                    rewritten = inspector.take()
                    if rewritten:
                        self.wfile.write(rewritten)
                        self.wfile.flush()
                    if failed:
                        self.close_connection = True
                else:
                    data = json.loads(b"".join(pending), parse_constant=reject_json_constant)
                    if not isinstance(data, dict):
                        raise ValueError("Response body must be a JSON object")
                    record_stream_error(data, request_id)
                    record_usage(data, request_id)
            finally:
                try:
                    if conn is not None:
                        conn.close()
                except OSError:
                    phase = "upstream_close"
                    raise
        except (ValueError, KeyError, OSError, http.client.HTTPException) as exc:
            if phase == "request_parse":
                event = "client_request_error"
            elif phase == "client_response":
                event = "client_response_error"
            else:
                FAILED = True
                event = "transport_error" if phase.startswith("upstream_") else "route_error"
            error_class = next((kind.__name__ for kind in type(exc).__mro__
                                if kind.__module__ in {"builtins", "http.client", "json.decoder"}),
                               "Exception")
            error_number = getattr(exc, "errno", None)
            metadata = {"event": event, "request_id": request_id, "at": time.time(),
                        "phase": phase, "error_class": error_class,
                        "errno": error_number if type(error_number) is int else None,
                        "route_failed": FAILED}
            if event == "route_error":
                metadata["status"] = 502
            diagnostic(metadata)
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
