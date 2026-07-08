from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from maki.api import mount_spa
from maki.main import app
from maki.schemas import ServicesResponse


def test_routers_resolve_and_are_not_shadowed_by_static_mount():
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    with patch("maki.inventory.routes.get_inventory_service") as factory:
        factory.return_value.get_inventory.return_value = ServicesResponse(
            services=[], generated_at=datetime(2026, 5, 29, tzinfo=UTC)
        )
        assert client.get("/api/services").status_code == 200


def _spa_app(tmp_path: Path) -> FastAPI:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>maki</title>MAKI_SPA_ROOT")
    (tmp_path / "assets" / "app.js").write_text("APP_JS_CONTENT")
    app = FastAPI()

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    mount_spa(app, tmp_path)
    return app


def test_deep_link_falls_back_to_index(tmp_path):
    client = TestClient(_spa_app(tmp_path))
    assert "MAKI_SPA_ROOT" in client.get("/").text
    # client-side route → index.html, not 404
    resp = client.get("/services/wfm-service")
    assert resp.status_code == 200
    assert "MAKI_SPA_ROOT" in resp.text


def test_real_asset_is_served_not_index(tmp_path):
    client = TestClient(_spa_app(tmp_path))
    resp = client.get("/assets/app.js")
    assert resp.status_code == 200
    assert resp.text == "APP_JS_CONTENT"


def test_api_route_not_shadowed_by_spa(tmp_path):
    client = TestClient(_spa_app(tmp_path))
    assert client.get("/api/ping").json() == {"ok": True}


def test_encoded_path_traversal_does_not_escape_static_dir(tmp_path):
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "assets").mkdir()
    (static_dir / "index.html").write_text("MAKI_SPA_ROOT")
    secret = tmp_path / "secret_outside.txt"
    secret.write_text("TOP_SECRET")

    app = FastAPI()
    mount_spa(app, static_dir)
    client = TestClient(app)

    for path in ("/%2e%2e/secret_outside.txt", "/..%2fsecret_outside.txt"):
        resp = client.get(path)
        # Traversal must not leak the out-of-tree file; falls back to index.
        assert "TOP_SECRET" not in resp.text
        assert "MAKI_SPA_ROOT" in resp.text
