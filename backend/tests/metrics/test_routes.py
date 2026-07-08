from datetime import UTC, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from maki.main import app
from maki.schemas import MetricBucket, MetricsResponse


def _fake():
    return MetricsResponse(
        range_days=30,
        service="all",
        deploy_count=2,
        deploys_per_day=0.07,
        lead_time_median_seconds=3600,
        trend=[MetricBucket(date="2026-05-30", count=2)],
        services=["inventory", "workforce"],
        generated_at=datetime(2026, 5, 31, tzinfo=UTC),
    )


def test_get_metrics_endpoint():
    with patch("maki.metrics.routes.get_metrics_service") as factory:
        factory.return_value.get_metrics.return_value = _fake()
        client = TestClient(app)
        r = client.get("/api/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["deploy_count"] == 2
    assert body["deploys_per_day"] == 0.07
    assert body["lead_time_median_seconds"] == 3600
    assert body["services"] == ["inventory", "workforce"]
    assert body["trend"][0] == {"date": "2026-05-30", "count": 2}


def test_passes_query_params_with_defaults():
    with patch("maki.metrics.routes.get_metrics_service") as factory:
        factory.return_value.get_metrics.return_value = _fake()
        client = TestClient(app)
        client.get("/api/metrics")
        factory.return_value.get_metrics.assert_called_once_with(30, "all", force=False)


def test_passes_query_params_explicit():
    with patch("maki.metrics.routes.get_metrics_service") as factory:
        factory.return_value.get_metrics.return_value = _fake()
        client = TestClient(app)
        client.get("/api/metrics?range_days=7&service=inventory&refresh=1")
        factory.return_value.get_metrics.assert_called_once_with(7, "inventory", force=True)


def test_range_days_zero_is_rejected():
    with patch("maki.metrics.routes.get_metrics_service") as factory:
        factory.return_value.get_metrics.return_value = _fake()
        client = TestClient(app)
        r = client.get("/api/metrics?range_days=0")
    assert r.status_code == 422


def test_range_days_negative_is_rejected():
    with patch("maki.metrics.routes.get_metrics_service") as factory:
        factory.return_value.get_metrics.return_value = _fake()
        client = TestClient(app)
        r = client.get("/api/metrics?range_days=-3")
    assert r.status_code == 422


def test_range_days_one_is_accepted():
    with patch("maki.metrics.routes.get_metrics_service") as factory:
        factory.return_value.get_metrics.return_value = _fake()
        client = TestClient(app)
        r = client.get("/api/metrics?range_days=1")
    assert r.status_code == 200
