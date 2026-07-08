import logging
from datetime import datetime

from maki.aws.images import sha_from_image
from maki.schemas import DeployRecord

logger = logging.getLogger(__name__)


class ECSDeployHistory:
    """Per-service deploy timeline from ECS task-definition revisions (newest first)."""

    def __init__(self, client):
        self._client = client
        self._record_by_arn: dict[str, DeployRecord] = {}  # immutable: a revision never changes

    def list_deploys(
        self,
        family: str,
        limit: int = 30,
        since: datetime | None = None,
        max_revisions: int | None = None,
    ) -> list[DeployRecord]:
        """Newest-first deploy records for a family.

        When ``since`` is None: return the newest ``limit`` revisions (count cap).
        When ``since`` is set: walk revisions newest->oldest and keep those registered at or
        after ``since``, stopping early at the first revision older than ``since`` (the list API
        is sorted DESC, so everything beyond it is older too). ``max_revisions`` caps worst-case
        fan-out; hitting it logs a warning rather than silently truncating.
        """
        if since is None:
            arns = self._list_revision_arns(family, limit)
            return [self._to_record(arn) for arn in arns]
        return self._list_deploys_since(family, since, max_revisions)

    def _list_deploys_since(
        self, family: str, since: datetime, max_revisions: int | None
    ) -> list[DeployRecord]:
        kept: list[DeployRecord] = []
        paginator = self._client.get_paginator("list_task_definitions")
        for page in paginator.paginate(familyPrefix=family, status="ACTIVE", sort="DESC"):
            for arn in page["taskDefinitionArns"]:
                record = self._to_record(arn)
                if record.registered_at is not None and record.registered_at < since:
                    return kept  # DESC order: this and every later revision is older than `since`
                kept.append(record)
                if max_revisions is not None and len(kept) >= max_revisions:
                    logger.warning(
                        "ECS deploy history for family %r hit max_revisions=%d within window "
                        "since %s; older in-window deploys are undercounted",
                        family,
                        max_revisions,
                        since.isoformat(),
                    )
                    return kept
        return kept

    def _list_revision_arns(self, family: str, limit: int) -> list[str]:
        arns: list[str] = []
        paginator = self._client.get_paginator("list_task_definitions")
        for page in paginator.paginate(familyPrefix=family, status="ACTIVE", sort="DESC"):
            arns.extend(page["taskDefinitionArns"])
            if len(arns) >= limit:
                break
        return arns[:limit]

    def _to_record(self, arn: str) -> DeployRecord:
        cached = self._record_by_arn.get(arn)
        if cached is None:
            td = self._client.describe_task_definition(taskDefinition=arn)["taskDefinition"]
            containers = td.get("containerDefinitions", [])
            image = containers[0]["image"] if containers else None
            cached = DeployRecord(
                sha=sha_from_image(image),
                image=image,
                revision=self._revision_from_arn(arn),
                registered_at=td.get("registeredAt"),
            )
            self._record_by_arn[arn] = cached
        # Return a fresh copy: callers (HistoryService) mutate author/message/commit_url
        # in place during enrichment, and a background SWR refresh must not race a
        # response the main thread is still serializing.
        return cached.model_copy()

    @staticmethod
    def family_from_arn(arn: str) -> str | None:
        """newsfeed family from 'arn:...:task-definition/newsfeed:5'."""
        if "task-definition/" not in arn:
            return None
        tail = arn.split("task-definition/", 1)[1]  # 'family:rev'
        return tail.split(":", 1)[0] or None

    @staticmethod
    def _revision_from_arn(arn: str) -> int | None:
        rev = arn.rsplit(":", 1)
        return int(rev[1]) if len(rev) == 2 and rev[1].isdigit() else None
