
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import errno
import http.client
import io
import json
import socket
import threading

import pytest

from test_route_classification import events, handler, load

QUOTA = b'data: {"error":{"message":"TEST-SECRET","type":"None","param":"None","code":429}}\n\n'
NORMAL = b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
DONE = b'data: [DONE]\n\n'


def install_reply(broker, chunks, headers=None):
    original = broker.http.client.HTTPConnection

    class Connection(original):
        def getresponse(self):
            reply = super().getresponse()
            pending = iter(chunks)
            reply.getheader = lambda name, default=None: {
                "Content-Type": "text/event-stream", **(headers or {})}.get(name, default)

            def read1(size):
                chunk = next(pending, b"")
                if isinstance(chunk, Exception):
                    raise chunk
                return chunk

            reply.read1 = read1
            return reply

    broker.http.client.HTTPConnection = Connection


def assert_failure(broker, calls, tmp_path, event, phase=None, error_class=None, error_number=None):
    recorded = events(tmp_path)
    error = recorded[-1]
    assert error["event"] == event
    admitted = [e for e in recorded if e["event"] == "admitted"]
    assert len(admitted) == 1
    assert error["request_id"] == admitted[0]["request_id"]
    assert any(e["event"] == "response" and e["status"] == 200
               and e["request_id"] == error["request_id"] for e in recorded)
    assert not any(e["event"] == "usage" for e in recorded)
    if phase is not None:
        assert error["phase"] == phase
        assert error["error_class"] == error_class
        assert error["errno"] == error_number
    assert broker.FAILED
    next_request = handler(broker)
    next_request.do_POST()
    assert next_request.errors[0][0] == 503
    assert len(calls) == 1
    assert "SECRET" not in (tmp_path / "diagnostic.jsonl").read_text()
    return error


@pytest.mark.parametrize("split", [1, 7, len(QUOTA) - 3])
@pytest.mark.parametrize("ending", ["complete", "no_delimiter", "truncated_json", "reset"])
def test_split_provider_proxy_quota_and_truncation(monkeypatch, tmp_path, split, ending):
    broker, calls = load(monkeypatch, tmp_path)
    wire = QUOTA if ending == "complete" else QUOTA[:-2] if ending == "no_delimiter" else QUOTA[:-6]
    split = min(split, len(wire) - 1)
    chunks = [wire[:split], wire[split:]]
    if ending == "reset":
        chunks.append(ConnectionResetError(errno.ECONNRESET, "TEST-SECRET"))
    install_reply(broker, chunks)
    handler(broker).do_POST()
    if ending == "reset":
        assert_failure(broker, calls, tmp_path, "transport_error", "upstream_read", "ConnectionResetError", errno.ECONNRESET)
    elif ending == "truncated_json":
        error = assert_failure(broker, calls, tmp_path, "route_error", "response_inspection", "JSONDecodeError")
        assert error["status"] == 502
        assert not any(e.get("quota_failure") for e in events(tmp_path))
    else:
        error = assert_failure(broker, calls, tmp_path, "stream_error")
        assert error["status"] == 429 and error["quota_failure"] is True


class WireSocket:
    def __init__(self, wire):
        self.wire = wire

    def makefile(self, mode):
        return io.BytesIO(self.wire)


@pytest.mark.parametrize("framing", ["chunk_incomplete", "chunk_invalid", "content_length_short"])
def test_real_http200_body_framing_failures(monkeypatch, tmp_path, framing):
    broker, calls = load(monkeypatch, tmp_path)
    if framing == "content_length_short":
        wire = b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: 1000\r\n\r\n' + NORMAL
    elif framing == "chunk_invalid":
        wire = b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\nZZ\r\n'
    else:
        wire = b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n100\r\n' + NORMAL
    reply = http.client.HTTPResponse(WireSocket(wire))
    reply.begin()
    original = broker.http.client.HTTPConnection

    class Connection(original):
        def getresponse(self):
            return reply

    broker.http.client.HTTPConnection = Connection
    handler(broker).do_POST()
    assert_failure(broker, calls, tmp_path, "transport_error", "upstream_read", "IncompleteRead")


@pytest.mark.parametrize("failure", ["reset", "broken_pipe"])
def test_same_response_different_socket_failure_direction(monkeypatch, tmp_path, failure):
    broker, calls = load(monkeypatch, tmp_path)
    chunks = [NORMAL]
    if failure == "reset":
        chunks.append(ConnectionResetError(errno.ECONNRESET, "TEST-SECRET"))
    else:
        chunks.append(DONE)
    install_reply(broker, chunks)
    request = handler(broker)
    if failure == "broken_pipe":
        class BrokenWriter:
            def write(self, data):
                raise BrokenPipeError(errno.EPIPE, "TEST-SECRET")
        request.wfile = BrokenWriter()
    request.do_POST()
    if failure == "reset":
        assert_failure(broker, calls, tmp_path, "transport_error", "upstream_read", "ConnectionResetError", errno.ECONNRESET)
    else:
        error = events(tmp_path)[-1]
        assert error["event"] == "client_response_error"
        assert error["phase"] == "client_response"
        assert error["error_class"] == "BrokenPipeError" and error["errno"] == errno.EPIPE
        assert error["request_id"] == events(tmp_path)[0]["request_id"]
        assert not broker.FAILED
        next_request = handler(broker)
        next_request.do_POST()
        assert not next_request.errors and len(calls) == 2
        assert "SECRET" not in (tmp_path / "diagnostic.jsonl").read_text()


@pytest.mark.parametrize("wire", [DONE, NORMAL + DONE, b': heartbeat\n\n' + NORMAL + DONE])
@pytest.mark.parametrize("framed", [False, True])
def test_valid_sse_control_streams(monkeypatch, tmp_path, wire, framed):
    broker, calls = load(monkeypatch, tmp_path)
    headers = {"Content-Length": str(len(wire))} if framed else None
    install_reply(broker, [wire[:3], wire[3:]], headers)
    handler(broker).do_POST()
    assert not broker.FAILED
    assert len(calls) == 1
    assert not any(e["event"].endswith("error") for e in events(tmp_path))


def test_recognized_quota_precedes_disconnected_writer(monkeypatch, tmp_path):
    broker, calls = load(monkeypatch, tmp_path)
    install_reply(broker, [QUOTA])
    request = handler(broker)

    class BrokenWriter:
        def write(self, data):
            raise BrokenPipeError(errno.EPIPE, "TEST-SECRET")

    request.wfile = BrokenWriter()
    request.do_POST()
    error = assert_failure(broker, calls, tmp_path, "stream_error")
    assert error["quota_failure"] and error["status"] == 429


@pytest.mark.parametrize("kind", ["invalid_sse", "short_length"])
def test_baseline_silently_accepts_demonstrated_incomplete_responses(monkeypatch, tmp_path, kind):
    broker, calls = load(monkeypatch, tmp_path, baseline=True)
    if kind == "invalid_sse":
        install_reply(broker, [QUOTA[:-6]])
    else:
        install_reply(broker, [NORMAL], {"Content-Length": "1000"})
    handler(broker).do_POST()
    assert not broker.FAILED
    assert [e["event"] for e in events(tmp_path)] == ["admitted", "response"]
    handler(broker).do_POST()
    assert len(calls) == 2


@pytest.mark.parametrize("exit_at", ["pacing", "after_headers"])
def test_prior_client_exits_during_paced_outstanding_request(monkeypatch, tmp_path, exit_at):
    broker, calls = load(monkeypatch, tmp_path)
    broker.MODEL = "claude-sonnet-5"
    broker.SPACING = 20
    monkeypatch.setenv("STUDY_SONNET_PACING", "1")
    monkeypatch.chdir(tmp_path)
    pacing_entered = threading.Event()
    admit = threading.Event()
    body_read = threading.Event()
    release_body = threading.Event()
    next_entered = threading.Event()
    pacing_calls = []
    thread_errors = []

    def reserve(path, spacing):
        pacing_calls.append(spacing)
        if len(pacing_calls) == 1:
            pacing_entered.set()
            assert admit.wait(3)

    broker.reserve_start = reserve
    original = broker.http.client.HTTPConnection

    class Connection(original):
        def getresponse(self):
            reply = super().getresponse()
            if len(calls) == 1:
                reply.getheader = lambda name, default=None: "text/event-stream" if name == "Content-Type" else default
                pending = iter([NORMAL, DONE, b""])

                def read1(size):
                    body_read.set()
                    assert release_body.wait(3)
                    return next(pending)

                reply.read1 = read1
            return reply

    broker.http.client.HTTPConnection = Connection
    start_post = broker.Handler.do_POST

    def tracked_post(self):
        if self.headers.get("X-Test-Client") == "next":
            next_entered.set()
        return start_post(self)

    monkeypatch.setattr(broker.Handler, "do_POST", tracked_post)
    body = json.dumps({"model": broker.MODEL}).encode()

    def send(client, marker):
        client.sendall(b'POST /v1/chat/completions HTTP/1.1\r\nHost: test\r\nConnection: close\r\nX-Test-Client: ' + marker + b'\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)

    next_response = []

    def next_client():
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(3)
                client.connect("route.sock")
                send(client, b"next")
                response = b""
                while True:
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                next_response.append(response)
        except BaseException as exc:
            thread_errors.append(exc)

    with broker.Server("route.sock", broker.Handler) as server:
        server_thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        server_thread.start()
        worker = None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as prior:
                prior.settimeout(3)
                prior.connect("route.sock")
                send(prior, b"prior")
                assert pacing_entered.wait(3)
                if exit_at == "after_headers":
                    admit.set()
                    headers = b""
                    while b"\r\n\r\n" not in headers:
                        headers += prior.recv(4096)
                    assert headers.startswith(b"HTTP/1.1 200")
                    assert body_read.wait(3)
            worker = threading.Thread(target=next_client)
            worker.start()
            assert next_entered.wait(3)
            assert len(calls) == (0 if exit_at == "pacing" else 1)
            admit.set()
            release_body.set()
            worker.join(3)
            assert not worker.is_alive() and not thread_errors
            assert next_response[0].startswith(b"HTTP/1.1 200")
            assert len(calls) == 2 and pacing_calls == [20, 20]
            recorded = events(tmp_path)
            admissions = [e for e in recorded if e["event"] == "admitted"]
            assert len(admissions) == 2
            first_id, next_id = [e["request_id"] for e in admissions]
            assert first_id != next_id
            error = next(e for e in recorded if e["event"] == "client_response_error")
            assert error["request_id"] == first_id
            assert error["phase"] == "client_response"
            assert error["error_class"] == "BrokenPipeError" and error["errno"] == errno.EPIPE
            assert not error["route_failed"] and not broker.FAILED
            assert any(e["event"] == "usage" and e["request_id"] == next_id for e in recorded)
            assert all(e["request_id"] in {first_id, next_id} for e in recorded)
            assert "SECRET" not in (tmp_path / "diagnostic.jsonl").read_text()
        finally:
            admit.set()
            release_body.set()
            if worker is not None:
                worker.join(3)
            server.shutdown()
            server_thread.join(3)
            assert not server_thread.is_alive()
