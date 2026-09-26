
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
from archive_gate import port as _archive_port
require_enabled()

import importlib.util
import io
import json
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/study"))


def load(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDY_ROUTE_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("STUDY_ROUTE_SOCKET", str(tmp_path / "route.sock"))
    monkeypatch.setenv("STUDY_SONNET_MIN_SPACING_S", "20")
    monkeypatch.setenv("STUDY_SONNET_PACING", "1")
    monkeypatch.setenv("STUDY_ROUTE_DIAGNOSTICS", str(tmp_path / "diagnostic.jsonl"))
    spec = importlib.util.spec_from_file_location("route_test", ROOT / "scripts/study/route_broker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_provider_b_route_rewrites_alias_to_verified_upstream(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDY_ROUTE_MODEL", "grok-4.6-route-b")
    monkeypatch.setenv("STUDY_ROUTE_SOCKET", str(tmp_path / "provider_b.sock"))
    spec = importlib.util.spec_from_file_location("provider_b_route_test", ROOT / "scripts/study/route_broker.py")
    broker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(broker)
    assert broker.ROUTE == {
        "host": _archive_setting('gateway_host_011'),
        "port": _archive_port('gateway_port_011'),
        "upstream_model": "grok-4.6",
        "path": "/v1/chat/completions",
    }


@pytest.mark.parametrize(
    "model,upstream,path",
    [
        ("grok-4.6-route-a", "grok-4-6", "/v1/chat/completions"),
        ("gpt-6-luna", "gpt-6-luna", "/v1/responses"),
        ("gpt-6-sol", "gpt-6-sol", "/v1/responses"),
        ("gpt-6-astra", "gpt-6-astra", "/v1/responses"),
        ("grok-4.6-route-b", "grok-4.6", "/v1/chat/completions"),
        ("claude-sonnet-5-route-b", "claude-sonnet-5", "/v1/chat/completions"),
        ("claude-opus-5-route-b", "claude-opus-5", "/v1/chat/completions"),
    ],
)
def test_provider_b_route_metadata(monkeypatch, tmp_path, model, upstream, path):
    monkeypatch.setenv("STUDY_ROUTE_MODEL", model)
    monkeypatch.setenv("STUDY_ROUTE_SOCKET", str(tmp_path / f"{model}.sock"))
    spec = importlib.util.spec_from_file_location(f"route_{model}", ROOT / "scripts/study/route_broker.py")
    broker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(broker)
    assert broker.ROUTE["upstream_model"] == upstream
    assert broker.ROUTE["path"] == path


def _handler(broker, body):
    handler = object.__new__(broker.Handler)
    handler.path = "/v1/chat/completions"
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.errors = []
    handler.send_error = lambda *args: handler.errors.append(args)
    handler.send_response = lambda *args: None
    handler.send_header = lambda *args: None
    handler.end_headers = lambda: None
    return handler


def test_http_502_retries_then_succeeds(monkeypatch, tmp_path):
    broker = load(monkeypatch, tmp_path)
    monkeypatch.setattr(broker, "TRANSIENT_TRIES", 3)
    monkeypatch.setattr(broker.time, "sleep", lambda *_: None)
    monkeypatch.setattr(broker, "reserve_start", lambda *a: 0)
    statuses = [502, 502, 200]
    calls = []

    class Reply:
        def __init__(self, status):
            self.status = status
        def getheader(self, name, default=None):
            return {"Content-Type": "application/json", "Content-Length": "2"}.get(name, default)
        def read(self):
            return b"{}"
        def read1(self, size):
            if self.status != 200:
                return b""
            data = getattr(self, "_body", b"{}")
            self._body = b""
            return data

    class Connection:
        def __init__(self, *args, **kwargs):
            pass
        def request(self, *args):
            calls.append(1)
        def getresponse(self):
            return Reply(statuses.pop(0))
        def close(self):
            pass

    monkeypatch.setattr(broker.http.client, "HTTPConnection", Connection)
    body = json.dumps({"model": broker.MODEL}).encode()
    handler = _handler(broker, body)
    handler.do_POST()
    assert calls == [1, 1, 1]
    assert not broker.FAILED
    events = [json.loads(line) for line in (tmp_path / "diagnostic.jsonl").read_text().splitlines()]
    assert [e["event"] for e in events if e["event"] in {"response", "transient_retry"}] == [
        "response", "transient_retry", "response", "transient_retry", "response",
    ]


def test_http_502_exhausted_latches(monkeypatch, tmp_path):
    broker = load(monkeypatch, tmp_path)
    monkeypatch.setattr(broker, "TRANSIENT_TRIES", 3)
    monkeypatch.setattr(broker.time, "sleep", lambda *_: None)
    monkeypatch.setattr(broker, "reserve_start", lambda *a: 0)
    calls = []

    class Reply:
        status = 502
        def getheader(self, name, default=None):
            return {"Content-Type": "application/json", "Content-Length": "0"}.get(name, default)
        def read(self):
            return b""
        def read1(self, size):
            return b""

    class Connection:
        def __init__(self, *args, **kwargs):
            pass
        def request(self, *args):
            calls.append(1)
        def getresponse(self):
            return Reply()
        def close(self):
            pass

    monkeypatch.setattr(broker.http.client, "HTTPConnection", Connection)
    body = json.dumps({"model": broker.MODEL}).encode()
    handler = _handler(broker, body)
    handler.do_POST()
    assert calls == [1, 1, 1] and broker.FAILED
    handler2 = _handler(broker, body)
    handler2.do_POST()
    assert handler2.errors[0][0] == 503 and calls == [1, 1, 1]


def test_quota_latches_upstream_and_logs_no_body(monkeypatch, tmp_path):
    broker = load(monkeypatch, tmp_path)
    starts, calls = [], []
    monkeypatch.setattr(broker, "reserve_start", lambda p, spacing: starts.append(spacing))
    class Reply:
        status = 429
        def getheader(self, name, default=None):
            return {"Retry-After": "120", "Content-Length": "0"}.get(name, default)
        def read1(self, size):
            return b""
    class Connection:
        def __init__(self, *args, **kwargs):
            pass
        def request(self, *args):
            calls.append(1)
        def getresponse(self):
            return Reply()
        def close(self):
            pass
    monkeypatch.setattr(broker.http.client, "HTTPConnection", Connection)
    handler = object.__new__(broker.Handler)
    body = json.dumps({"model": broker.MODEL, "messages": [{"content": "SECRET-BODY"}]}).encode()
    handler.path = "/v1/chat/completions"
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    errors = []
    handler.send_error = lambda *args: errors.append(args)
    handler.send_response = lambda *args: None
    handler.send_header = lambda *args: None
    handler.end_headers = lambda: None
    handler.do_POST()
    handler.do_POST()
    assert calls == [1] and starts == [20]
    assert errors[0][0] == 503
    text = (tmp_path / "diagnostic.jsonl").read_text()
    assert "SECRET" not in text and "Authorization" not in text
    assert json.loads(text.splitlines()[1])["retry_after_s"] == 120


def test_usage_only_numeric_allowlist(monkeypatch, tmp_path):
    broker = load(monkeypatch, tmp_path)
    broker.record_usage(json.dumps({"usage": {"prompt_tokens": 12, "secret": "hidden",
        "completion_tokens_details": {"reasoning_tokens": 3, "secret": "hidden"}}}).encode(), "request")
    text = (tmp_path / "diagnostic.jsonl").read_text()
    assert "hidden" not in text and "secret" not in text
    assert json.loads(text)["usage"]["prompt_tokens"] == 12


@pytest.mark.parametrize('payload,quota', [
    ({'error':{'type':'rate_limit_error','message':'SECRET'}}, True),
    ({'error':{'code':429,'message':'SECRET'}}, True),
    ({'error':{'type':'server_error','message':'SECRET quota 429'}}, False),
    ({'type':'error','error':{'code':'resource_exhausted'}}, True),
])
def test_stream_error_split_chunks_sanitized(monkeypatch, tmp_path, payload, quota):
    broker = load(monkeypatch, tmp_path)
    inspector = broker.SSEInspector('test')
    wire = b'data: ' + json.dumps(payload).encode() + b'\r\n\r\n'
    assert not inspector.feed(wire[:15])
    assert inspector.feed(wire[15:])
    assert broker.FAILED
    text = (tmp_path/'diagnostic.jsonl').read_text()
    assert 'SECRET' not in text
    record = json.loads(text)
    assert record['quota_failure'] is quota
    assert record['status'] == (429 if quota else 502)


def test_missing_choice_delta_is_filled_for_grok_cli(monkeypatch, tmp_path):
    broker = load(monkeypatch, tmp_path)
    inspector = broker.SSEInspector("delta")
    assert not inspector.feed(b'data: {"choices":[{"index":0,"finish_reason":"stop"}]}\n\n')
    out = inspector.take()
    payload = json.loads(out.split(b"data: ", 1)[1])
    assert payload["choices"][0]["delta"] == {}
    assert payload["choices"][0]["finish_reason"] == "stop"


def test_responses_api_event_name_is_preserved(monkeypatch, tmp_path):
    broker = load(monkeypatch, tmp_path)
    inspector = broker.SSEInspector("responses")
    wire = b'event: response.output_item.added\ndata: {"type":"response.output_item.added","item":{"type":"function_call"}}\n\n'
    assert not inspector.feed(wire)
    assert inspector.take() == wire
    assert not broker.FAILED
    events = [json.loads(line) for line in (tmp_path / "diagnostic.jsonl").read_text().splitlines()]
    assert any(e.get("event") == "sse_event" and e.get("name") == "response.output_item.added" for e in events)


def test_responses_api_event_name_survives_split_chunks(monkeypatch, tmp_path):
    broker = load(monkeypatch, tmp_path)
    inspector = broker.SSEInspector("responses-split")
    wire = b'event: response.function_call_arguments.done\r\ndata: {"type":"response.function_call_arguments.done","arguments":"{}"}\r\n\r\n'
    for byte in wire:
        assert not inspector.feed(bytes([byte]))
    assert inspector.take() == wire.replace(b"\r", b"")


def test_provider_a_keepalive_event_is_filtered(monkeypatch, tmp_path):
    broker = load(monkeypatch, tmp_path)
    inspector = broker.SSEInspector("heartbeat")
    assert not inspector.feed(b'event: keepalive\ndata: {}\n\n')
    assert inspector.take() == b""
    assert not broker.FAILED


def test_event_error_and_normal_content_distinguished(monkeypatch, tmp_path):
    broker = load(monkeypatch, tmp_path)
    normal = broker.SSEInspector('normal')
    assert not normal.feed(b'data: {"choices":[{"delta":{"content":"error quota 429"}}]}\n\n')
    assert not broker.FAILED
    error = broker.SSEInspector('error')
    assert error.feed(b'event: error\ndata: SECRET\n\n')
    assert error.take() == b""
    assert 'SECRET' not in (tmp_path/'diagnostic.jsonl').read_text()


def test_http200_sse_error_latches_and_blocks_second_request(monkeypatch, tmp_path):
    broker = load(monkeypatch, tmp_path)
    monkeypatch.setattr(broker, 'reserve_start', lambda *a: 0)
    calls = []
    class Reply:
        status = 200
        def __init__(self):
            self.chunks = iter([b'data: {"error":{"code":429,"message":"SECRET"}}\n\n', b''])
        def getheader(self, name, default=None):
            return 'text/event-stream' if name == 'Content-Type' else default
        def read1(self, size):
            return next(self.chunks)
    class Connection:
        def __init__(self, *a, **k):
            pass
        def request(self, *a):
            calls.append(1)
        def getresponse(self):
            return Reply()
        def close(self):
            pass
    monkeypatch.setattr(broker.http.client, 'HTTPConnection', Connection)
    handler = object.__new__(broker.Handler)
    body = json.dumps({'model':broker.MODEL}).encode()
    handler.path = '/v1/chat/completions'
    handler.headers = {'Content-Length':str(len(body))}
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    errors = []
    handler.send_error = lambda *a: errors.append(a)
    handler.send_response = lambda *a: None
    handler.send_header = lambda *a: None
    handler.end_headers = lambda: None
    handler.do_POST()
    handler.do_POST()
    assert calls == [1] and errors[0][0] == 503
    assert handler.close_connection
    assert b'SECRET' not in handler.wfile.getvalue()
    assert 'SECRET' not in (tmp_path/'diagnostic.jsonl').read_text()
