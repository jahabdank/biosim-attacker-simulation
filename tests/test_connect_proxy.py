import importlib.util
from pathlib import Path

import pytest


PATH = Path(__file__).resolve().parents[1] / "scripts/study/connect_proxy.py"
spec = importlib.util.spec_from_file_location("connect_proxy", PATH)
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


def test_reject_private_dns(monkeypatch):
    monkeypatch.setattr(proxy.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError, match="nonpublic"):
        proxy.public_addresses("api.x.ai")


def test_reject_mixed_dns(monkeypatch):
    monkeypatch.setattr(proxy.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("1.1.1.1", 443)), (2, 1, 6, "", ("169.254.169.254", 443))])
    with pytest.raises(ValueError):
        proxy.public_addresses("api.x.ai")


def test_only_explicit_hosts():
    assert "auth.x.ai" in proxy.ALLOWED
    assert "127.0.0.1" not in proxy.ALLOWED
    assert "example.com" not in proxy.ALLOWED
