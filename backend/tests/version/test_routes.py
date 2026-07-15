from unittest.mock import patch

from fastapi.testclient import TestClient

import maki.version.routes as version_routes
from maki.main import app
from maki.schemas import VersionResponse


def fresh_client() -> TestClient:
    version_routes.get_version_service.cache_clear()  # drop the cached service + its warm SwrCache
    return TestClient(app)


def test_returns_check_result():
    fake = VersionResponse(
        current_sha="aaa", upstream="origin/main", behind_by=4, update_available=True
    )
    with patch("maki.version.routes.get_version_service") as factory:
        factory.return_value.get_version.return_value = fake
        client = TestClient(app)
        r = client.get("/api/version")
    assert r.status_code == 200
    assert r.json() == {
        "current_sha": "aaa",
        "upstream": "origin/main",
        "behind_by": 4,
        "update_available": True,
    }


def test_result_is_cached_between_requests():
    with patch("maki.version.service.check_version", return_value=VersionResponse()) as check:
        client = fresh_client()
        client.get("/api/version")
        client.get("/api/version")
    check.assert_called_once()


def test_stale_cache_rechecks():
    service = version_routes.get_version_service
    service.cache_clear()
    swr = service()._cache
    stale = VersionResponse(current_sha="old")
    latest = VersionResponse(current_sha="ccc", update_available=True)
    with patch("maki.version.service.check_version", side_effect=[stale, latest]):
        client = TestClient(app)
        assert client.get("/api/version").json()["current_sha"] == "old"
        # Rewind the entry past the stale bound so the next read blocks + re-checks.
        ts, value = swr._entries["version"]
        swr._entries["version"] = (ts - 2 * version_routes.RECHECK_SECONDS, value)
        assert client.get("/api/version").json()["current_sha"] == "ccc"
