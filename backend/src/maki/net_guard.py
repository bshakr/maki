# backend/src/maki/net_guard.py
"""Loopback bind guard.

maki has no auth by default and serves live prod read data (incl. plaintext env-var values), so it
must not be reachable off-box by accident. Binding a loopback address is an OS-level guarantee that
off-box packets are dropped. This guard refuses any non-loopback bind unless the operator opts in
with MAKI_ALLOW_NETWORK_BIND=1 (e.g. inside a container, where 0.0.0.0 is required and the real
control is the host publish scope).
"""

import ipaddress

_LOOPBACK_NAMES = {"localhost"}


class NetworkBindError(RuntimeError):
    """Raised when maki would bind a non-loopback interface without an explicit opt-in."""


def is_loopback(host: str) -> bool:
    """True if ``host`` is a loopback name or address. IPv6 brackets are tolerated (``[::1]``)."""
    h = host.strip().strip("[]")
    if h in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def assert_safe_bind(host: str, *, allow_network_bind: bool) -> None:
    """Raise NetworkBindError if ``host`` is non-loopback and the network-bind opt-in is off."""
    if is_loopback(host) or allow_network_bind:
        return
    raise NetworkBindError(
        f"refusing to bind {host!r}: not a loopback address. maki has no auth by default and "
        "serves live prod read data. To bind a non-loopback interface deliberately, set "
        "MAKI_ALLOW_NETWORK_BIND=1 (and front it with auth or a trusted proxy)."
    )
