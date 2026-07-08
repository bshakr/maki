# backend/src/maki/auth.py
"""Optional shared-bearer-token gate for the HTTP surface.

Enabled only when MAKI_AUTH_TOKEN is set (off by default — the laptop case needs no auth). When on,
every /api/* request must carry ``Authorization: Bearer <token>``; the health check, the SPA shell
and assets, and /api/config (so the SPA can discover auth is required and show its login gate) are
exempt. The token is never logged and never sent to the client.
"""

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_EXEMPT_PATHS = {"/health", "/api/config"}


def is_auth_exempt(path: str) -> bool:
    """True for paths reachable without a token: health, the config bootstrap, and the SPA shell."""
    if path in _EXEMPT_PATHS:
        return True
    return not path.startswith("/api/")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next):
        if is_auth_exempt(request.url.path):
            return await call_next(request)
        header = request.headers.get("authorization", "")
        scheme, _, presented = header.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(presented, self._token):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)
