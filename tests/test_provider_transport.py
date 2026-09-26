"""Local-only wire tests for both API formats and the trusted relay boundary."""
import http.client
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import socket
import threading

import pytest
from biosim_operator.provider_config import credential, load_provider

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def upstream():
    requests = []
    settings = {"status": 200, "body": b'{"choices":[],"usage":{"completion_tokens":1}}', "type": "application/json"}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            requests.append((self.path, dict(self.headers), json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            self.send_response(settings['status'])
            if settings['status'] == 302:
                self.send_header('Location', 'http://127.0.0.1:1/never')
            self.send_header('Content-Type', settings['type'])
            self.send_header('Content-Length', str(len(settings['body'])))
            self.end_headers()
            self.wfile.write(settings['body'])
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_port, settings, requests
    server.shutdown()
    server.server_close()
    thread.join()


def broker(monkeypatch, tmp_path, port, backend='chat_completions', key=True):
    config = tmp_path / 'providers.toml'
    secret = tmp_path / 'secret'
    if key:
        secret.write_text('synthetic-credential')
    config.write_text(f'''[models."test-model"]
kind="api"
model="upstream-model"
context_window=10000
max_completion_tokens=1000
api_backend="{backend}"
base_url="http://127.0.0.1:{port}/v1"
credential_file="{secret}"
auth_header="api-key"
auth_prefix=""
''')
    monkeypatch.setenv('BIOSIM_PROVIDERS', str(config))
    monkeypatch.setenv('STUDY_ROUTE_MODEL', 'test-model')
    monkeypatch.setenv('STUDY_ROUTE_SOCKET', str(tmp_path/'route.sock'))
    monkeypatch.setenv('STUDY_ROUTE_DIAGNOSTICS', str(tmp_path/'diagnostics.jsonl'))
    monkeypatch.setenv('STUDY_ROUTE_TRANSIENT_TRIES', '1')
    monkeypatch.setenv('STUDY_ROUTE_PACING', '0')
    spec = importlib.util.spec_from_file_location('wire_broker', ROOT/'scripts/study/route_broker.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def post(module, tmp_path):
    path = str(tmp_path/'listen.sock')
    server = module.Server(path, module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    class UnixHTTP(http.client.HTTPConnection):
        def connect(self):
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(3)
            self.sock.connect(path)
    try:
        with closing(UnixHTTP('localhost')) as connection:
            connection.request('POST', module.ROUTE['path'], json.dumps({'model':'test-model','stream':True}), {'Content-Type':'application/json'})
            response = connection.getresponse()
            return response.status, response.read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        Path(path).unlink(missing_ok=True)


def test_latched_route_consumes_bounded_body_before_rejection(monkeypatch, tmp_path):
    import io
    module=broker(monkeypatch,tmp_path,1)
    module.FAILED=True
    handler=object.__new__(module.Handler)
    payload=b'{"model":"test-model"}'
    handler.path=module.ROUTE['path']
    handler.headers={'Content-Length':str(len(payload))}
    handler.rfile=io.BytesIO(payload)
    replies=[]
    handler.send_error=lambda status,*args: replies.append((status,handler.rfile.tell()))
    handler.do_POST()
    assert replies==[(503,len(payload))]


def test_latched_route_keeps_request_size_limit(monkeypatch, tmp_path):
    import io
    module=broker(monkeypatch,tmp_path,1)
    module.FAILED=True
    handler=object.__new__(module.Handler)
    handler.path=module.ROUTE['path']
    handler.headers={'Content-Length':'16000001'}
    handler.rfile=io.BytesIO(b'')
    replies=[]
    handler.send_error=lambda status,*args: replies.append(status)
    handler.do_POST()
    assert replies==[413] and handler.rfile.tell()==0


@pytest.mark.parametrize('backend', ['chat_completions','responses'])
def test_both_api_formats_and_credentials(monkeypatch, tmp_path, upstream, backend):
    port, settings, requests = upstream
    module = broker(monkeypatch, tmp_path, port, backend)
    if backend == 'responses':
        settings.update(type='text/event-stream', body=b'event: keepalive\ndata: {}\n\nevent: response.completed\ndata: {"type":"response.completed"}\n\n')
    else:
        settings.update(type='text/event-stream', body=b'data: {"choices":[{"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    status, body = post(module, tmp_path)
    assert status == 200
    assert requests[0][0] == '/v1/' + ('responses' if backend == 'responses' else 'chat/completions')
    assert requests[0][1]['api-key'] == 'synthetic-credential'
    assert requests[0][2]['model'] == 'upstream-model'
    if backend == 'responses':
        assert b'event: response.completed' in body and b'keepalive' not in body
    else:
        assert b'"delta":{}' in body and b'[DONE]' in body
    assert 'synthetic-credential' not in (tmp_path/'diagnostics.jsonl').read_text()


@pytest.mark.parametrize('status', [302, 401, 429, 500])
def test_errors_and_redirects_never_forward_raw_body(monkeypatch, tmp_path, upstream, status):
    port, settings, requests = upstream
    settings.update(status=status, body=b'synthetic-private-upstream-diagnostic')
    module = broker(monkeypatch, tmp_path, port)
    result, body = post(module, tmp_path)
    assert result >= 400 and module.FAILED
    assert b'synthetic-private' not in body
    assert len(requests) == 1
    assert 'synthetic-private' not in (tmp_path/'diagnostics.jsonl').read_text()


def test_missing_empty_credentials_fail_before_upstream(monkeypatch, tmp_path, upstream):
    port, _, requests = upstream
    broker(monkeypatch, tmp_path, port, key=False)
    provider = load_provider('test-model')
    with pytest.raises(ValueError, match='unavailable'):
        credential(provider)
    (tmp_path/'secret').write_text('')
    with pytest.raises(ValueError, match='empty'):
        credential(provider)
    assert not requests


def test_split_sse_failure_and_responses_event(monkeypatch, tmp_path, upstream):
    module = broker(monkeypatch, tmp_path, upstream[0], 'responses')
    inspector = module.SSEInspector('synthetic')
    wire = b'event: response.output_text.delta\ndata: {"delta":"text"}\n\n'
    for byte in wire:
        assert not inspector.feed(bytes([byte]))
    assert b'event: response.output_text.delta' in inspector.take()
    assert inspector.feed(b'event: error\ndata: {"error":{"code":"429","message":"private-detail"}}\n\n')
    assert module.FAILED and b'private-detail' not in inspector.take()


def test_http200_error_envelope_does_not_leak_message(monkeypatch, tmp_path, upstream):
    port, settings, _ = upstream
    settings.update(body=b'{"error":{"message":"synthetic-private-detail","code":"invalid_request"}}')
    module = broker(monkeypatch, tmp_path, port)
    status, body = post(module, tmp_path)
    assert status == 502 and module.FAILED
    assert b'synthetic-private-detail' not in body
    assert 'synthetic-private-detail' not in (tmp_path/'diagnostics.jsonl').read_text()


@pytest.mark.parametrize('event_name', ['response.failed','message'])
def test_r7_nested_responses_failure_latches_next_request(monkeypatch, tmp_path, upstream, event_name):
    from recovery_diagnostics import failure_reason
    port, settings, requests = upstream
    wire = ('event: ' + event_name + '\ndata: {"type":"response.failed","response":{"status":"failed","error":{"code":"rate_limit_exceeded","message":"synthetic-private-details"}}}\n\n').encode()
    settings.update(type='text/event-stream',body=wire)
    module=broker(monkeypatch,tmp_path,port,'responses')
    status,body=post(module,tmp_path)
    assert status==200 and module.FAILED
    assert b'synthetic-private-details' not in body
    assert failure_reason(tmp_path/'diagnostics.jsonl',active=False)=='quota'
    status,_=post(module,tmp_path)
    assert status==503 and len(requests)==1
    assert 'synthetic-private-details' not in (tmp_path/'diagnostics.jsonl').read_text()
