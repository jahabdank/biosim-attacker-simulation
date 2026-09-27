"""Broker must not die on set_flow args; value aliases desired_flow_rate."""
from __future__ import annotations

from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()


import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "scripts" / "study" / "eclss_broker.py"


def _load():
    spec = importlib.util.spec_from_file_location("eclss_broker", SPEC)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_set_flow_value_alias_does_not_call_bare_fn(monkeypatch):
    mod = _load()
    seen = {}

    def fake_set_flow(**kwargs):
        seen.update(kwargs)
        return '{"ok": true}'

    monkeypatch.setattr(mod, "_tools", lambda: {"set_flow": fake_set_flow})
    reply = mod.handle(
        {
            "op": "call",
            "name": "set_flow",
            "arguments": {
                "module": "IMV-LAB-GAL",
                "side": "consumers",
                "resource": "Power",
                "value": 1.0,
            },
        }
    )
    assert reply.get("isError") is not True
    assert seen["desired_flow_rate"] == 1.0
    assert "value" not in seen


def test_set_flow_typeerror_does_not_raise():
    mod = _load()
    reply = mod.handle(
        {
            "op": "call",
            "name": "set_flow",
            "arguments": {"module": "ogs"},
        }
    )
    assert reply.get("isError") is True
    text = reply["content"][0]["text"]
    assert "bad arguments" in text


def test_denied_tool_does_not_raise():
    mod = _load()
    reply = mod.handle({"op": "call", "name": "advance_time"})
    assert reply.get("isError") is True
    assert "not on this panel" in reply["content"][0]["text"]
