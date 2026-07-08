from collections.abc import Callable
from datetime import UTC, datetime

from maki.aws.amplify_registry import AmplifyDeployRegistry
from maki.aws.ecs_registry import ECSDeployRegistry
from maki.cache import SwrCache
from maki.github_enrich import GitHubEnricher
from maki.schemas import DeployedService, ServicesResponse


class InventoryService:
    def __init__(
        self,
        ecs: ECSDeployRegistry,
        amplify: AmplifyDeployRegistry | None,
        enricher: GitHubEnricher,
        repo_for: Callable[[str], str | None],
        fresh_seconds: float,
        stale_seconds: float,
    ):
        self._ecs = ecs
        self._amplify = amplify
        self._enricher = enricher
        self._repo_for = repo_for
        self._cache = SwrCache(fresh_seconds, stale_seconds)

    def get_inventory(self, force: bool = False) -> ServicesResponse:
        return self._cache.get("inventory", self._compute, force=force)

    def _compute(self) -> ServicesResponse:
        services = self._ecs.list_deployed_services()
        if self._amplify is not None:
            web = self._amplify.get_deployed_web_app()
            if web is not None:
                services.append(web)
        for svc in services:
            svc.commit_url = self._commit_url(svc)
            self._enrich(svc)
        return ServicesResponse(
            services=sorted(services, key=lambda s: s.name),
            generated_at=datetime.now(UTC),
        )

    def _commit_url(self, svc: DeployedService) -> str | None:
        repo = self._repo_for(svc.name)
        if not svc.git_sha or repo is None:
            return None
        return f"https://github.com/{repo}/commit/{svc.git_sha}"

    def _enrich(self, svc: DeployedService) -> None:
        # Best-effort GitHub enrichment; failures/None leave the fields untouched.
        repo = self._repo_for(svc.name)
        if not svc.git_sha or repo is None:
            return
        info = self._enricher.commit(repo, svc.git_sha)
        if info is None:
            return
        svc.author = info.author
        svc.author_avatar_url = info.author_avatar_url
        svc.message = info.message
        svc.pr_url = info.pr_url
        svc.committed_at = info.committed_at
