# backend/tests/test_cors_closed.py
from fastapi.testclient import TestClient

from maki.api import app


def test_no_wildcard_cors_on_simple_get():
    client = TestClient(app)
    r = client.get("/health")
    assert r.headers.get("access-control-allow-origin") != "*"


def test_no_cors_headers_on_cross_origin_preflight():
    client = TestClient(app)
    r = client.options(
        "/api/config",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # With no CORS middleware, there is no permissive allow-origin echoing the attacker origin.
    assert r.headers.get("access-control-allow-origin") not in ("*", "https://evil.example.com")
