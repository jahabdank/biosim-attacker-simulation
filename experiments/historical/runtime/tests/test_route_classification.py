
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import errno
import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
import threading
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/study"))


def load(monkeypatch, tmp_path, baseline=False):
    monkeypatch.setenv("STUDY_ROUTE_MODEL", "gpt-5.6-luna")
    monkeypatch.setenv("STUDY_ROUTE_SOCKET", str(tmp_path / "route.sock"))
    monkeypatch.setenv("STUDY_ROUTE_DIAGNOSTICS", str(tmp_path / "diagnostic.jsonl"))
    monkeypatch.setenv("ROUTE_A_HARNESS_API_KEY", "TEST-SECRET-KEY")
    monkeypatch.setenv("STUDY_SONNET_PACING", "0")
    root = ROOT / "tests/fixtures/next46_baseline" if baseline else ROOT
    spec = importlib.util.spec_from_file_location("classification_broker", root / "scripts/study/route_broker.py")
    broker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(broker)
    calls = []

    class Reply:
        status = 200

        def __init__(self):
            self.body = io.BytesIO(b'{"usage":{"completion_tokens":3}}')

        def getheader(self, name, default=None):
            return {"Content-Type": "application/json"}.get(name, default)

        def read1(self, size):
            return self.body.read(size)

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args):
            calls.append(args)

        def getresponse(self):
            return Reply()

        def close(self):
            pass

    # Replace only the broker's module reference; no network provider is reachable.
    broker.http = SimpleNamespace(client=SimpleNamespace(
        HTTPConnection=Connection, HTTPException=broker.http.client.HTTPException,
        IncompleteRead=broker.http.client.IncompleteRead))
    return broker, calls


def handler(broker, raw=None, length=None):
    if raw is None:
        raw = json.dumps({"model": broker.MODEL}).encode()
    result = object.__new__(broker.Handler)
    result.path = "/v1/chat/completions"
    result.headers = {"Content-Length": str(len(raw)) if length is None else length}
    result.rfile = io.BytesIO(raw)
    result.wfile = io.BytesIO()
    result.errors = []
    result.send_error = lambda *args: result.errors.append(args)
    result.send_response = lambda *args: None
    result.send_header = lambda *args: None
    result.end_headers = lambda: None
    return result


def events(tmp_path):
    return [json.loads(line) for line in (tmp_path / "diagnostic.jsonl").read_text().splitlines()]


@pytest.mark.parametrize("raw,length", [
    (b'{"secret":"TEST-SECRET-BODY"', None),
    (b"", "20"),
    (b'{"model":', "80"),
    (b"{}", "TEST-SECRET-LENGTH"),
])
@pytest.mark.parametrize("baseline", [True, False])
def test_success_then_unadmitted_bad_request_then_valid(monkeypatch, tmp_path, raw, length, baseline):
    broker, calls = load(monkeypatch, tmp_path, baseline)
    handler(broker).do_POST()
    handler(broker, raw, length).do_POST()
    recorded = events(tmp_path)
    error = recorded[-1]
    assert error["request_id"] != recorded[-2]["request_id"]
    assert not any(e["event"] == "admitted" and e["request_id"] == error["request_id"] for e in recorded)
    assert recorded[-2]["event"] == "usage"
    assert error["event"] == ("transport_error" if baseline else "client_request_error")
    assert broker.FAILED is baseline
    next_request = handler(broker)
    next_request.do_POST()
    assert len(calls) == (1 if baseline else 2)
    assert bool(next_request.errors) is baseline
    if baseline:
        assert next_request.errors[0][0] == 503
    else:
        assert error["phase"] == "request_parse"
        assert error["error_class"] in {"ValueError", "JSONDecodeError"}
        assert error["errno"] is None
        assert error["route_failed"] is False
    assert "TEST-SECRET" not in (tmp_path / "diagnostic.jsonl").read_text()


@pytest.mark.parametrize("raw,length", [(b"", "0"), (b"null", None), (b"[]", None)])
def test_empty_and_nonobject_requests_do_not_poison_route(monkeypatch, tmp_path, raw, length):
    broker, calls = load(monkeypatch, tmp_path)
    handler(broker, raw, length).do_POST()
    assert not broker.FAILED
    handler(broker).do_POST()
    assert len(calls) == 1


@pytest.mark.parametrize("phase", ["request_parse", "client_response"])
def test_client_socket_errors_are_sanitized_and_do_not_latch(monkeypatch, tmp_path, phase):
    broker, calls = load(monkeypatch, tmp_path)
    request = handler(broker)

    class BrokenStream:
        def read(self, size):
            raise ConnectionResetError(errno.ECONNRESET, "TEST-SECRET-BODY")

        def write(self, data):
            raise BrokenPipeError(errno.EPIPE, "TEST-SECRET-KEY")

    if phase == "request_parse":
        request.rfile = BrokenStream()
    else:
        request.wfile = BrokenStream()
    request.do_POST()
    error = events(tmp_path)[-1]
    assert error["phase"] == phase
    assert error["errno"] == (errno.ECONNRESET if phase == "request_parse" else errno.EPIPE)
    assert error["error_class"] == ("ConnectionResetError" if phase == "request_parse" else "BrokenPipeError")
    assert not broker.FAILED
    handler(broker).do_POST()
    assert len(calls) == (1 if phase == "request_parse" else 2)
    assert "TEST-SECRET" not in (tmp_path / "diagnostic.jsonl").read_text()


@pytest.mark.parametrize("phase", ["upstream_request", "upstream_response", "upstream_read", "upstream_close"])
def test_upstream_socket_errors_still_latch(monkeypatch, tmp_path, phase):
    broker, calls = load(monkeypatch, tmp_path)
    monkeypatch.setattr(broker.time, "sleep", lambda *_: None)
    original = broker.http.client.HTTPConnection

    class BrokenConnection(original):
        def request(self, *args):
            super().request(*args)
            if phase == "upstream_request":
                raise ConnectionRefusedError(errno.ECONNREFUSED, "TEST-SECRET")

        def getresponse(self):
            if phase == "upstream_response":
                raise ConnectionResetError(errno.ECONNRESET, "TEST-SECRET")
            reply = super().getresponse()

            def fail_read(size):
                raise TimeoutError(errno.ETIMEDOUT, "TEST-SECRET")

            if phase == "upstream_read":
                reply.read1 = fail_read
            return reply

        def close(self):
            if phase == "upstream_close":
                raise ConnectionResetError(errno.ECONNRESET, "TEST-SECRET")

    broker.http.client.HTTPConnection = BrokenConnection
    handler(broker).do_POST()
    error = events(tmp_path)[-1]
    assert error["event"] == "transport_error"
    assert error["phase"] == phase
    assert error["route_failed"] is True
    next_request = handler(broker)
    next_request.do_POST()
    expected_calls = 3 if phase in {"upstream_request", "upstream_response"} else 1
    assert len(calls) == expected_calls and next_request.errors[0][0] == 503
    assert "TEST-SECRET" not in (tmp_path / "diagnostic.jsonl").read_text()


def test_missing_trusted_credential_is_not_a_client_error(monkeypatch, tmp_path):
    broker, calls = load(monkeypatch, tmp_path)
    monkeypatch.delenv("ROUTE_A_HARNESS_API_KEY")
    handler(broker).do_POST()
    error = events(tmp_path)[-1]
    assert error["event"] == "route_error"
    assert error["phase"] == "admission"
    assert error["error_class"] == "KeyError"
    assert error["status"] == 502
    assert broker.FAILED and not calls


def test_exception_subclass_and_errno_cannot_leak_text(monkeypatch, tmp_path):
    broker, calls = load(monkeypatch, tmp_path)
    secret_error = type("TEST_SECRET_CLASS", (OSError,), {})

    class BrokenStream:
        def read(self, size):
            exc = secret_error("TEST-SECRET-MESSAGE")
            exc.errno = "TEST-SECRET-ERRNO"
            raise exc

    request = handler(broker)
    request.rfile = BrokenStream()
    request.do_POST()
    error = events(tmp_path)[-1]
    assert error["error_class"] == "OSError"
    assert error["errno"] is None
    assert "SECRET" not in (tmp_path / "diagnostic.jsonl").read_text()
    assert not calls and not broker.FAILED


@pytest.mark.parametrize("status,wire", [
    (429, b'{"error":{"code":429,"message":"TEST-SECRET"}}'),
    (200, b'data: {"error":{"type":"server_error","message":"TEST-SECRET"}}\n\n'),
    (200, b'data: {"error":{"code":429,"message":"TEST-SECRET"}}\n\n'),
])
def test_provider_http_and_sse_failures_still_latch(monkeypatch, tmp_path, status, wire):
    broker, calls = load(monkeypatch, tmp_path)
    original = broker.http.client.HTTPConnection

    class ErrorConnection(original):
        def getresponse(self):
            reply = super().getresponse()
            reply.status = status
            reply.body = io.BytesIO(wire)
            reply.getheader = lambda name, default=None: (
                "text/event-stream" if name == "Content-Type" and status == 200 else default)
            return reply

    broker.http.client.HTTPConnection = ErrorConnection
    handler(broker).do_POST()
    assert broker.FAILED
    next_request = handler(broker)
    next_request.do_POST()
    assert len(calls) == 1 and next_request.errors[0][0] == 503
    assert any(e.get("status", 0) >= 400 for e in events(tmp_path))
    assert "TEST-SECRET" not in (tmp_path / "diagnostic.jsonl").read_text()


def nonstream_reply(broker, wire):
    original = broker.http.client.HTTPConnection

    class Connection(original):
        def getresponse(self):
            reply = super().getresponse()
            reply.body = io.BytesIO(wire)
            reply.getheader = lambda name, default=None: {
                "Content-Type": "application/json", "Content-Length": str(len(wire))}.get(name, default)
            return reply

    broker.http.client.HTTPConnection = Connection


@pytest.mark.parametrize("wire", [
    b"{}", b'{"arbitrary":{"nested":[null,true,12]}}',
    b' {"choices":[{"message":{"content":"TEST-SECRET"}}],"usage":{"completion_tokens":3}}\n',
    b'{"content":"' + b'x' * 2_000_001 + b'"}',
])
def test_nonstream_valid_objects_preserve_exact_bytes(monkeypatch, tmp_path, wire):
    broker, calls = load(monkeypatch, tmp_path)
    nonstream_reply(broker, wire)
    request = handler(broker)
    request.do_POST()
    assert request.wfile.getvalue() == wire
    assert not broker.FAILED and len(calls) == 1
    assert not any(e["event"].endswith("error") for e in events(tmp_path))
    assert "TEST-SECRET" not in (tmp_path / "diagnostic.jsonl").read_text()


@pytest.mark.parametrize("wire", [
    b"", b" \r\n", b'{"content":"TEST-SECRET"', b'{malformed: "TEST-SECRET"}',
    b"[]", b"null", b'"TEST-SECRET"', b"1", b"true",
    b'{"value":NaN}', b'{"value":Infinity}', b'{"value":-Infinity}',
    b'{"content":"\xff"}', b'{}{}',
])
def test_nonstream_invalid_body_latches_sanitized_route_error(monkeypatch, tmp_path, wire):
    broker, calls = load(monkeypatch, tmp_path)
    nonstream_reply(broker, wire)
    handler(broker).do_POST()
    recorded = events(tmp_path)
    error = recorded[-1]
    assert error["event"] == "route_error" and error["phase"] == "response_inspection"
    assert error["status"] == 502 and error["route_failed"] is True
    assert error["request_id"] == recorded[0]["request_id"]
    assert error["error_class"] in {"JSONDecodeError", "ValueError", "UnicodeDecodeError"}
    assert not any(e.get("quota_failure") or e["event"] == "usage" for e in recorded)
    assert broker.FAILED
    next_request = handler(broker)
    next_request.do_POST()
    assert len(calls) == 1 and next_request.errors[0][0] == 503
    assert "TEST-SECRET" not in (tmp_path / "diagnostic.jsonl").read_text()


@pytest.mark.parametrize("code,expected", [(429, 429), (500, 502)])
def test_nonstream_error_object_classified_and_preserved(monkeypatch, tmp_path, code, expected):
    broker, calls = load(monkeypatch, tmp_path)
    wire = json.dumps({"error": {"code": code, "message": "TEST-SECRET"}}).encode()
    nonstream_reply(broker, wire)
    request = handler(broker)
    request.do_POST()
    assert request.wfile.getvalue() == wire
    error = events(tmp_path)[-1]
    assert error["event"] == "stream_error" and error["status"] == expected
    assert error["quota_failure"] is (code == 429)
    assert broker.FAILED and len(calls) == 1
    assert "TEST-SECRET" not in (tmp_path / "diagnostic.jsonl").read_text()


@pytest.mark.parametrize("baseline", [True, False])
def test_real_unix_socket_truncated_body_then_next_request(monkeypatch, tmp_path, baseline):
    broker, calls = load(monkeypatch, tmp_path, baseline)
    monkeypatch.chdir(tmp_path)
    socket_path = "route.sock"
    with broker.Server(socket_path, broker.Handler) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(2)
                client.connect(socket_path)
                client.sendall(b'POST /v1/chat/completions HTTP/1.1\r\nHost: test\r\nContent-Length: 50\r\n\r\n{"model":')
                client.shutdown(socket.SHUT_WR)
                assert client.recv(4096) == b""
            body = json.dumps({"model": broker.MODEL}).encode()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(2)
                client.connect(socket_path)
                client.sendall(b'POST /v1/chat/completions HTTP/1.1\r\nHost: test\r\nConnection: close\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
                response = b""
                while True:
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    response += chunk
            assert response.startswith(b"HTTP/1.1 503" if baseline else b"HTTP/1.1 200")
            assert len(calls) == (0 if baseline else 1)
        finally:
            server.shutdown()
            thread.join(timeout=2)
            assert not thread.is_alive()
