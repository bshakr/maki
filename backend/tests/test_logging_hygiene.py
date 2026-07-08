# backend/tests/test_logging_hygiene.py
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from maki.api import app
from maki.auth import BearerAuthMiddleware


def test_no_custom_body_logging_middleware():
    # The only BaseHTTPMiddleware maki adds is the (optional) auth gate. Any other custom
    # BaseHTTPMiddleware is a red flag for body/response logging — fail so it gets reviewed.
    custom = [
        m.cls.__name__
        for m in app.user_middleware
        if isinstance(m.cls, type)
        and issubclass(m.cls, BaseHTTPMiddleware)
        and m.cls is not BearerAuthMiddleware
    ]
    assert custom == [], f"unexpected BaseHTTPMiddleware (possible body logging): {custom}"


def test_auth_failure_does_not_log_the_token(caplog):
    sub = FastAPI()

    @sub.get("/api/secret")
    def secret():
        return {"ok": True}

    sub.add_middleware(BearerAuthMiddleware, token="super-secret-token")
    client = TestClient(sub, headers={"Authorization": "Bearer super-secret-token"})
    with caplog.at_level(logging.DEBUG):
        client.get("/api/secret")
    assert "super-secret-token" not in caplog.text
