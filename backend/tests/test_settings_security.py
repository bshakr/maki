# backend/tests/test_settings_security.py
from maki.settings import Settings


def test_auth_disabled_by_default():
    s = Settings()
    assert s.auth_token is None
    assert s.auth_required is False


def test_auth_token_from_env(monkeypatch):
    monkeypatch.setenv("MAKI_AUTH_TOKEN", "sekret")
    s = Settings()
    assert s.auth_token == "sekret"
    assert s.auth_required is True


def test_trusted_hosts_defaults_to_loopback(monkeypatch):
    monkeypatch.delenv("MAKI_ALLOWED_HOSTS", raising=False)
    s = Settings()
    assert s.trusted_hosts == ["localhost", "127.0.0.1", "[::1]"]


def test_trusted_hosts_extends_with_env(monkeypatch):
    monkeypatch.setenv("MAKI_ALLOWED_HOSTS", "maki.internal, box.lan")
    s = Settings()
    assert s.trusted_hosts == ["localhost", "127.0.0.1", "[::1]", "maki.internal", "box.lan"]


def test_allow_network_bind_from_env(monkeypatch):
    monkeypatch.setenv("MAKI_ALLOW_NETWORK_BIND", "1")
    assert Settings().allow_network_bind is True
