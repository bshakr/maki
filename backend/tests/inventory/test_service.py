from datetime import UTC, datetime
from unittest.mock import MagicMock

from maki.inventory.service import InventoryService
from maki.schemas import CommitInfo, DeployedService


def _svc(name, platform="ecs"):
    return DeployedService(name=name, platform=platform, git_sha="sha1")


def _repo_for(name: str) -> str:
    return {"middleware": "acme/middleware", "web-app": "acme/web-app"}.get(
        name, "acme/platform"
    )


def _enricher(commit_info=None):
    enricher = MagicMock()
    enricher.commit.return_value = commit_info
    return enricher


def test_combines_ecs_and_amplify_and_adds_commit_urls():
    ecs = MagicMock()
    ecs.list_deployed_services.return_value = [_svc("newsfeed"), _svc("middleware")]
    amplify = MagicMock()
    amplify.get_deployed_web_app.return_value = _svc("web-app", platform="amplify")
    svc = InventoryService(
        ecs, amplify, _enricher(), repo_for=_repo_for, fresh_seconds=0, stale_seconds=0
    )
    result = svc.get_inventory()
    by_name = {s.name: s for s in result.services}
    assert by_name["newsfeed"].commit_url == "https://github.com/acme/platform/commit/sha1"
    assert (
        by_name["middleware"].commit_url == "https://github.com/acme/middleware/commit/sha1"
    )
    assert by_name["web-app"].commit_url == "https://github.com/acme/web-app/commit/sha1"


def test_amplify_disabled_yields_only_ecs_services():
    ecs = MagicMock()
    ecs.list_deployed_services.return_value = [_svc("newsfeed"), _svc("middleware")]
    svc = InventoryService(
        ecs, None, _enricher(), repo_for=_repo_for, fresh_seconds=0, stale_seconds=0
    )
    result = svc.get_inventory()
    names = {s.name for s in result.services}
    assert names == {"newsfeed", "middleware"}
    assert all(s.platform == "ecs" for s in result.services)


def test_amplify_disabled_never_calls_amplify_client():
    ecs = MagicMock()
    ecs.list_deployed_services.return_value = [_svc("newsfeed")]
    amplify = MagicMock()
    svc = InventoryService(
        ecs, None, _enricher(), repo_for=_repo_for, fresh_seconds=0, stale_seconds=0
    )
    svc.get_inventory()
    amplify.get_deployed_web_app.assert_not_called()


def test_amplify_enabled_appends_web_app_row():
    ecs = MagicMock()
    ecs.list_deployed_services.return_value = [_svc("newsfeed")]
    amplify = MagicMock()
    amplify.get_deployed_web_app.return_value = _svc("storefront", platform="amplify")
    svc = InventoryService(
        ecs, amplify, _enricher(), repo_for=_repo_for, fresh_seconds=0, stale_seconds=0
    )
    result = svc.get_inventory()
    by_name = {s.name: s for s in result.services}
    assert by_name["storefront"].platform == "amplify"


def test_enriches_author_message_and_pr_url():
    ecs = MagicMock()
    ecs.list_deployed_services.return_value = [_svc("newsfeed")]
    amplify = MagicMock()
    amplify.get_deployed_web_app.return_value = None
    committed_at = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)
    enricher = _enricher(
        CommitInfo(
            author="bailey",
            author_avatar_url="https://avatars.githubusercontent.com/u/1?v=4",
            message="feat: do the thing",
            pr_url="https://github.com/acme/platform/pull/42",
            committed_at=committed_at,
        )
    )
    svc = InventoryService(
        ecs, amplify, enricher, repo_for=_repo_for, fresh_seconds=0, stale_seconds=0
    )
    result = svc.get_inventory()
    newsfeed = result.services[0]
    assert newsfeed.author == "bailey"
    assert newsfeed.author_avatar_url == "https://avatars.githubusercontent.com/u/1?v=4"
    assert newsfeed.message == "feat: do the thing"
    assert newsfeed.pr_url == "https://github.com/acme/platform/pull/42"
    assert newsfeed.committed_at == committed_at
    enricher.commit.assert_called_once_with("acme/platform", "sha1")


def test_enricher_none_leaves_fields_none():
    ecs = MagicMock()
    ecs.list_deployed_services.return_value = [_svc("newsfeed")]
    amplify = MagicMock()
    amplify.get_deployed_web_app.return_value = None
    svc = InventoryService(
        ecs, amplify, _enricher(None), repo_for=_repo_for, fresh_seconds=0, stale_seconds=0
    )
    result = svc.get_inventory()
    newsfeed = result.services[0]
    assert newsfeed.author is None
    assert newsfeed.message is None
    assert newsfeed.pr_url is None
    # commit_url is still derived locally, independent of the enricher.
    assert newsfeed.commit_url == "https://github.com/acme/platform/commit/sha1"


def test_unmapped_service_has_no_commit_url_and_no_enrichment():
    ecs = MagicMock()
    ecs.list_deployed_services.return_value = [_svc("mystery")]
    amplify = MagicMock()
    amplify.get_deployed_web_app.return_value = None
    enricher = _enricher(
        CommitInfo(author="bailey", message="feat: ignored", committed_at=None)
    )
    svc = InventoryService(
        ecs,
        amplify,
        enricher,
        repo_for=lambda _n: None,
        fresh_seconds=0,
        stale_seconds=0,
    )
    result = svc.get_inventory()
    mystery = result.services[0]
    assert mystery.commit_url is None
    assert mystery.author is None
    assert mystery.message is None
    enricher.commit.assert_not_called()


def test_serves_cached_within_fresh_window():
    ecs = MagicMock()
    ecs.list_deployed_services.return_value = [_svc("newsfeed")]
    amplify = MagicMock()
    amplify.get_deployed_web_app.return_value = None
    svc = InventoryService(
        ecs, amplify, _enricher(), repo_for=_repo_for, fresh_seconds=60, stale_seconds=300
    )
    svc.get_inventory()
    svc.get_inventory()
    assert ecs.list_deployed_services.call_count == 1


def test_force_bypasses_cache():
    ecs = MagicMock()
    ecs.list_deployed_services.return_value = [_svc("newsfeed")]
    amplify = MagicMock()
    amplify.get_deployed_web_app.return_value = None
    svc = InventoryService(
        ecs, amplify, _enricher(), repo_for=_repo_for, fresh_seconds=60, stale_seconds=300
    )
    svc.get_inventory()
    svc.get_inventory(force=True)
    assert ecs.list_deployed_services.call_count == 2
