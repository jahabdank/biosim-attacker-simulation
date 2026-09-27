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
    provider = tmp_path / 'provider.toml'
    provider.write_text('[models."gpt-5.6-luna"]\nkind="api"\napi_backend="chat_completions"\nbase_url="http://127.0.0.1:9/v1"\ncontext_window=1050000\nmax_completion_tokens=8192\nallow_unauthenticated=true\n')
    monkeypatch.setenv("BIOSIM_PROVIDERS", str(provider))
    monkeypatch.setenv("STUDY_ROUTE_TRANSIENT_TRIES", "1")
    monkeypatch.setenv("STUDY_SONNET_PACING", "0")
    root = ROOT
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


