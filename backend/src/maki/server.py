# backend/src/maki/server.py
"""maki's supported launch entrypoint: ``python -m maki.server``.

Owns the bind so the loopback guard runs before any socket is opened. Host/port/reload come from
the environment (defaults: 127.0.0.1:8787, reload off). uvicorn imports the app from the
``maki.main:app`` import string, so this module never imports the app itself.
"""

import os

import uvicorn

from maki.net_guard import assert_safe_bind


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    host = os.environ.get("MAKI_HOST", "127.0.0.1")
    port = int(os.environ.get("MAKI_PORT", "8787"))
    reload = _env_bool("MAKI_RELOAD")
    assert_safe_bind(host, allow_network_bind=_env_bool("MAKI_ALLOW_NETWORK_BIND"))
    uvicorn.run("maki.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
