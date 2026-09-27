"""Characterize staged relay parsing without contacting any upstream."""

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import importlib.util
import io
from pathlib import Path
import sys

import pytest

RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY / 'scripts/study'))
spec = importlib.util.spec_from_file_location('relay_review_helpers', RELAY / 'tests/test_route_classification.py')
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)
assert helpers.ROOT == RELAY


@pytest.mark.parametrize('wire', [
    b': heartbeat\n\ndata: [DONE]\n\n',
    b'event: message\r\ndata: {"choices": []}\r\n\r\n',
    b'data: {"choices":\ndata: []}\n\n',
    b'data: {"choices": []}\n\n',
    b'data: {"choices": []}',
])
def test_valid_json_sse_framing_not_overconstrained(monkeypatch, tmp_path, wire):
    broker, _ = helpers.load(monkeypatch, tmp_path)
    inspector = broker.SSEInspector('synthetic')
    for byte in wire:
        assert not inspector.feed(bytes([byte]))
    assert not inspector.feed(b'', final=True)
    assert not broker.FAILED


@pytest.mark.parametrize('wire', [b'data: {"choices":', b'data: plain-text\n\n', b'data:\n\n'])
def test_sse_json_requirement_is_chat_route_specific(monkeypatch, tmp_path, wire):
    broker, _ = helpers.load(monkeypatch, tmp_path)
    inspector = broker.SSEInspector('synthetic')
    with pytest.raises(ValueError):
        inspector.feed(wire)
        inspector.feed(b'', final=True)


@pytest.mark.parametrize('wire,valid', [(b'{"choices":[],"usage":{"completion_tokens":1}}', True), (b'{malformed-json', False), (b'', False)])
def test_nonstream_response_passthrough_characterization(monkeypatch, tmp_path, wire, valid):
    broker, calls = helpers.load(monkeypatch, tmp_path)
    original = broker.http.client.HTTPConnection
    class Connection(original):
        def getresponse(self):
            reply = super().getresponse()
            reply.body = io.BytesIO(wire)
            reply.getheader = lambda name, default=None: {
                'Content-Type': 'application/json', 'Content-Length': str(len(wire))}.get(name, default)
            return reply
    broker.http.client.HTTPConnection = Connection
    request = helpers.handler(broker)
    request.do_POST()
    assert request.wfile.getvalue() == wire
    assert broker.FAILED is not valid and len(calls) == 1
    errors = [e for e in helpers.events(tmp_path) if e['event'].endswith('error')]
    if valid:
        assert not errors
    else:
        assert len(errors) == 1 and errors[0]['event'] == 'route_error'
        assert errors[0]['status'] == 502
