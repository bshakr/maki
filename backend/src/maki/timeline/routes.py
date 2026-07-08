from datetime import datetime
from functools import cache

from fastapi import APIRouter

from maki.aws.clients import ecs_client
from maki.aws.service_deployments import ECSServiceDeployments
from maki.github_actions import GitHubActions
from maki.github_enrich import GitHubEnricher
from maki.inventory.routes import get_inventory_service
from maki.schemas import DeployTimeline, PullDescription
from maki.settings import settings
from maki.timeline.service import TimelineService

router = APIRouter(prefix="/api")

# Pull a slightly-over-600-char body down to a clean ~600-char excerpt at a word boundary.
_EXCERPT_LIMIT = 600


@cache
def get_timeline_service() -> TimelineService:
    client = ecs_client()
    timeline = settings.config.deployTimeline
    return TimelineService(
        inventory=get_inventory_service(),
        ecs_client=client,
        cluster=settings.ecs_cluster,
        service_deployments=ECSServiceDeployments(client, settings.ecs_cluster),
        actions=GitHubActions(token=settings.github_token, base_url=settings.github_api_url),
        repo_for=settings.repo_for,
        fresh_seconds=settings.swr_fresh_seconds,
        stale_seconds=settings.swr_stale_seconds,
        rollout_suffixes=tuple(timeline.github.hideJobsEndingWith),
        rollout_prefixes=tuple(timeline.github.hideJobsStartingWith),
        group_matrix_jobs=timeline.github.groupMatrixJobs,
        enabled=timeline.enabled,
    )


@cache
def get_pull_enricher() -> GitHubEnricher:
    return GitHubEnricher(token=settings.github_token, base_url=settings.github_api_url)


def _excerpt(body: str | None) -> str | None:
    """First ~600 chars of ``body``, trimmed at a word boundary, '…' suffix if truncated."""
    if not body:
        return None
    text = body.strip()
    if len(text) <= _EXCERPT_LIMIT:
        return text
    head = text[:_EXCERPT_LIMIT]
    cut = head.rsplit(" ", 1)[0].rstrip() or head.rstrip()
    return f"{cut}…"


@router.get("/services/{name}/deploy-timeline", response_model=DeployTimeline)
def get_deploy_timeline(
    name: str,
    sha: str | None = None,
    revision: int | None = None,
    merged_at: datetime | None = None,
    refresh: bool = False,
) -> DeployTimeline:
    return get_timeline_service().get_timeline(
        name, sha=sha, revision=revision, merged_at=merged_at, force=refresh
    )


@router.get("/services/{name}/pull", response_model=PullDescription)
def get_pull(name: str, number: int) -> PullDescription:
    repo = settings.repo_for(name)
    if repo is None:
        return PullDescription(number=number, title=None, body_excerpt=None, url=None)
    url = f"https://github.com/{repo}/pull/{number}"
    pull = get_pull_enricher().pull(repo, number)
    if not pull:
        return PullDescription(number=number, title=None, body_excerpt=None, url=url)
    return PullDescription(
        number=number,
        title=pull.get("title"),
        body_excerpt=_excerpt(pull.get("body")),
        url=url,
    )
