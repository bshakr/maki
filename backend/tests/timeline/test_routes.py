from datetime import UTC, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from maki.main import app
from maki.schemas import DeployTimeline, TimelineSegment


def _timeline():
    return DeployTimeline(
        service="wfm-service",
        sha="cf930b6",
        merged_at=datetime(2026, 5, 29, 4, 0, tzinfo=UTC),
        live_at=datetime(2026, 5, 29, 7, 0, tzinfo=UTC),
        total_seconds=10800,
        segments=[
            TimelineSegment(
                key="ci:build",
                label="Build",
                source="github_actions",
                start=datetime(2026, 5, 29, 4, 0, tzinfo=UTC),
                end=datetime(2026, 5, 29, 4, 0, 38, tzinfo=UTC),
                seconds=38,
                status="success",
            )
        ],
        generated_at=datetime(2026, 5, 29, 7, 0, tzinfo=UTC),
    )


def test_endpoint_returns_200_and_shape():
    with patch("maki.timeline.routes.get_timeline_service") as factory:
        factory.return_value.get_timeline.return_value = _timeline()
        r = TestClient(app).get("/api/services/wfm-service/deploy-timeline")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "wfm-service"
    assert body["sha"] == "cf930b6"
    assert body["total_seconds"] == 10800
    assert body["segments"][0]["key"] == "ci:build"
    assert body["segments"][0]["source"] == "github_actions"
    assert body["segments"][0]["status"] == "success"


def test_refresh_query_forces_recompute():
    with patch("maki.timeline.routes.get_timeline_service") as factory:
        factory.return_value.get_timeline.return_value = _timeline()
        TestClient(app).get("/api/services/wfm-service/deploy-timeline?refresh=1")
        factory.return_value.get_timeline.assert_called_once_with(
            "wfm-service", sha=None, revision=None, merged_at=None, force=True
        )


def test_default_does_not_force():
    with patch("maki.timeline.routes.get_timeline_service") as factory:
        factory.return_value.get_timeline.return_value = _timeline()
        TestClient(app).get("/api/services/wfm-service/deploy-timeline")
        factory.return_value.get_timeline.assert_called_once_with(
            "wfm-service", sha=None, revision=None, merged_at=None, force=False
        )


def test_sha_and_revision_query_params_passed_through():
    with patch("maki.timeline.routes.get_timeline_service") as factory:
        factory.return_value.get_timeline.return_value = _timeline()
        TestClient(app).get(
            "/api/services/wfm-service/deploy-timeline?sha=deadbeef&revision=42"
        )
        factory.return_value.get_timeline.assert_called_once_with(
            "wfm-service", sha="deadbeef", revision=42, merged_at=None, force=False
        )


def test_pull_endpoint_returns_title_and_excerpt():
    with patch("maki.timeline.routes.get_pull_enricher") as factory:
        factory.return_value.pull.return_value = {
            "title": "feat(wfm): anchor shifts",
            "body": "Short body.",
        }
        r = TestClient(app).get("/api/services/wfm-service/pull?number=4242")
    assert r.status_code == 200
    body = r.json()
    assert body["number"] == 4242
    assert body["title"] == "feat(wfm): anchor shifts"
    assert body["body_excerpt"] == "Short body."
    assert body["url"] == "https://github.com/acme/platform/pull/4242"
    factory.return_value.pull.assert_called_once_with("acme/platform", 4242)


def test_pull_endpoint_degrades_to_nulls_on_failure():
    with patch("maki.timeline.routes.get_pull_enricher") as factory:
        factory.return_value.pull.return_value = None
        r = TestClient(app).get("/api/services/wfm-service/pull?number=99")
    assert r.status_code == 200
    body = r.json()
    assert body["number"] == 99
    assert body["title"] is None
    assert body["body_excerpt"] is None
    assert body["url"] == "https://github.com/acme/platform/pull/99"


def test_pull_endpoint_unmapped_service_returns_null_url_without_enrichment():
    with patch("maki.timeline.routes.get_pull_enricher") as factory:
        r = TestClient(app).get("/api/services/mystery-service/pull?number=7")
    assert r.status_code == 200
    body = r.json()
    assert body["url"] is None
    assert body["title"] is None
    factory.return_value.pull.assert_not_called()


def test_pull_endpoint_truncates_long_body_at_word_boundary():
    long_body = "word " * 200  # 1000 chars, well over the 600 limit
    with patch("maki.timeline.routes.get_pull_enricher") as factory:
        factory.return_value.pull.return_value = {"title": "t", "body": long_body}
        r = TestClient(app).get("/api/services/wfm-service/pull?number=7")
    excerpt = r.json()["body_excerpt"]
    assert excerpt.endswith("…")
    assert len(excerpt) <= 601  # 600 chars + ellipsis at most
    assert not excerpt[:-1].endswith(" ")  # trimmed at a word boundary
