# backend/tests/test_net_guard.py
import pytest

from maki.net_guard import NetworkBindError, assert_safe_bind, is_loopback


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "[::1]", "127.5.5.5"])
def test_loopback_hosts_recognised(host):
    assert is_loopback(host) is True


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "maki.internal", ""])
def test_non_loopback_hosts(host):
    assert is_loopback(host) is False


def test_loopback_bind_allowed():
    assert_safe_bind("127.0.0.1", allow_network_bind=False)  # no raise


def test_non_loopback_refused_without_optin():
    with pytest.raises(NetworkBindError) as exc:
        assert_safe_bind("0.0.0.0", allow_network_bind=False)
    assert "0.0.0.0" in str(exc.value)
    assert "MAKI_ALLOW_NETWORK_BIND" in str(exc.value)


def test_non_loopback_allowed_with_optin():
    assert_safe_bind("0.0.0.0", allow_network_bind=True)  # no raise
