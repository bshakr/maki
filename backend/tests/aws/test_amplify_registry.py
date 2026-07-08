from datetime import UTC, datetime
from unittest.mock import MagicMock

from maki.aws.amplify_registry import AmplifyDeployRegistry


def test_returns_web_app_with_active_commit():
    end_time = datetime(2026, 5, 29, 8, 0, tzinfo=UTC)
    client = MagicMock()
    client.get_branch.return_value = {"branch": {"activeJobId": "42"}}
    client.get_job.return_value = {
        "job": {"summary": {"commitId": "deadbeefsha", "status": "SUCCEED", "endTime": end_time}}
    }
    registry = AmplifyDeployRegistry(client, app_id="dexampleapp123", branch="master")
    svc = registry.get_deployed_web_app()
    assert svc.name == "web-app"
    assert svc.platform == "amplify"
    assert svc.git_sha == "deadbeefsha"
    assert svc.status == "SUCCEED"
    assert svc.deployed_at == end_time


def test_name_comes_from_configured_service_name():
    client = MagicMock()
    client.get_branch.return_value = {"branch": {"activeJobId": "42"}}
    client.get_job.return_value = {
        "job": {"summary": {"commitId": "sha", "status": "SUCCEED", "endTime": None}}
    }
    registry = AmplifyDeployRegistry(
        client, app_id="x", branch="master", service_name="storefront"
    )
    svc = registry.get_deployed_web_app()
    assert svc.name == "storefront"


def test_returns_none_when_no_active_job():
    client = MagicMock()
    client.get_branch.return_value = {"branch": {}}
    registry = AmplifyDeployRegistry(client, app_id="x", branch="master")
    assert registry.get_deployed_web_app() is None
