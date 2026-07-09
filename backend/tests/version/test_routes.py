from unittest.mock import patch

from fastapi.testclient import TestClient

import maki.version.routes as version_routes
from maki.main import app
from maki.schemas import VersionResponse


def get_version(fake: VersionResponse):
    version_routes._cached = None
    with patch("maki.version.routes.check_version", return_value=fake) as check:
        client = TestClient(app)
        first = client.get("/api/version")
        second = client.get("/api/version")
    return first, second, check


def test_returns_check_result():
    fake = VersionResponse(
        current_sha="aaa", upstream="origin/main", behind_by=4, update_available=True
    )
    r, _, _ = get_version(fake)
    assert r.status_code == 200
    assert r.json() == {
        "current_sha": "aaa",
        "upstream": "origin/main",
        "behind_by": 4,
        "update_available": True,
    }


def test_result_is_cached_between_requests():
    _, second, check = get_version(VersionResponse())
    assert second.status_code == 200
    check.assert_called_once()


def test_stale_cache_rechecks():
    # Negative sentinel: monotonic() is always >= 0, so this entry is guaranteed stale.
    version_routes._cached = (-2 * version_routes.RECHECK_SECONDS, VersionResponse())
    fresh = VersionResponse(current_sha="ccc", update_available=True)
    with patch("maki.version.routes.check_version", return_value=fresh):
        client = TestClient(app)
        r = client.get("/api/version")
    assert r.json()["current_sha"] == "ccc"
