# backend/tests/test_server_launcher.py
import pytest

from maki import server
from maki.net_guard import NetworkBindError


def test_main_defaults_to_loopback(monkeypatch):
    calls = {}
    monkeypatch.setattr(server.uvicorn, "run", lambda *a, **k: calls.update(args=a, kw=k))
    monkeypatch.delenv("MAKI_HOST", raising=False)
    monkeypatch.delenv("MAKI_PORT", raising=False)
    monkeypatch.delenv("MAKI_ALLOW_NETWORK_BIND", raising=False)
    server.main()
    assert calls["args"] == ("maki.main:app",)
    assert calls["kw"]["host"] == "127.0.0.1"
    assert calls["kw"]["port"] == 8787


def test_main_refuses_non_loopback_without_optin(monkeypatch):
    monkeypatch.setattr(server.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setenv("MAKI_HOST", "0.0.0.0")
    monkeypatch.delenv("MAKI_ALLOW_NETWORK_BIND", raising=False)
    with pytest.raises(NetworkBindError):
        server.main()


def test_main_allows_non_loopback_with_optin(monkeypatch):
    calls = {}
    monkeypatch.setattr(server.uvicorn, "run", lambda *a, **k: calls.update(kw=k))
    monkeypatch.setenv("MAKI_HOST", "0.0.0.0")
    monkeypatch.setenv("MAKI_ALLOW_NETWORK_BIND", "1")
    server.main()
    assert calls["kw"]["host"] == "0.0.0.0"
