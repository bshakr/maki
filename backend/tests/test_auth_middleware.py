# backend/tests/test_auth_middleware.py
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maki.auth import BearerAuthMiddleware, is_auth_exempt


def _app(token: str) -> FastAPI:
    app = FastAPI()

    @app.get("/api/secret")
    def secret():
        return {"ok": True}

    @app.get("/api/config")
    def config():
        return {"auth_required": True}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.add_middleware(BearerAuthMiddleware, token=token)
    return app


def test_exempt_paths():
    assert is_auth_exempt("/health") is True
    assert is_auth_exempt("/api/config") is True
    assert is_auth_exempt("/assets/app.js") is True  # non-/api → SPA shell
    assert is_auth_exempt("/api/services") is False


def test_protected_path_401_without_token():
    client = TestClient(_app("sekret"))
    assert client.get("/api/secret").status_code == 401


def test_protected_path_200_with_correct_token():
    client = TestClient(_app("sekret"), headers={"Authorization": "Bearer sekret"})
    assert client.get("/api/secret").status_code == 200


def test_protected_path_401_with_wrong_token():
    client = TestClient(_app("sekret"), headers={"Authorization": "Bearer nope"})
    assert client.get("/api/secret").status_code == 401


def test_exempt_paths_reachable_without_token():
    client = TestClient(_app("sekret"))
    assert client.get("/health").status_code == 200
    assert client.get("/api/config").status_code == 200
