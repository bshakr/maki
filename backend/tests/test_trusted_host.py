# backend/tests/test_trusted_host.py
from fastapi.testclient import TestClient

from maki.api import app


def test_allowed_host_passes():
    client = TestClient(app)  # Host: testserver, allowed via conftest
    assert client.get("/health").status_code == 200


def test_disallowed_host_rejected():
    client = TestClient(app, headers={"host": "evil.example.com"})
    r = client.get("/health")
    assert r.status_code == 400


def test_loopback_host_allowed():
    client = TestClient(app, headers={"host": "127.0.0.1"})
    assert client.get("/health").status_code == 200
