import logging
from datetime import UTC, datetime, timedelta

from maki.aws.ecs_history import ECSDeployHistory

logger = logging.getLogger(__name__)

_DESCRIBE_BATCH = 20  # describe_service_revisions caps serviceRevisionArns at 20
_DEFAULT_LOOKBACK = timedelta(days=90)  # ECS retains service-deployment records ~90 days

# createdAt is always present on a service deployment brief; the sentinel only guards a malformed
# record so the max()/comparison logic stays total-ordered.
_EPOCH = datetime.min.replace(tzinfo=UTC)


def _created(brief: dict) -> datetime:
    created = brief.get("createdAt")
    return created if isinstance(created, datetime) else _EPOCH


class ECSServiceDeployments:
    """Resolve when each task-def revision fully reached production, from ECS service deployments.

    Uses ``ListServiceDeployments`` (the rollout records, retained ~90 days) +
    ``DescribeServiceRevisions`` to map a completed deployment's ``finishedAt`` onto the
    task-definition revision int it shipped. ``finishedAt`` is the moment the rollout fully
    completed in production, so it is the correct "live" timestamp for lead time.
    """

    def __init__(self, client, cluster: str):
        self._client = client
        self._cluster = cluster

    def state_by_revision(
        self, service_name: str, since: datetime, family: str
    ) -> dict[int, dict]:
        """Map ``{task_def_revision: {"finished_at": datetime|None, "status": str|None}}``.

        Keeps the NEWEST brief per target revision so the reported ``status`` reflects the latest
        known rollout state — including in-progress and rollback states that have no ``finishedAt``
        yet. The ingester uses it to persist both the live-in-prod time and the rollout status in
        one pass.

        Best-effort: ANY failure (unsupported boto3, AccessDenied, throttling, parse error)
        returns ``{}`` and logs a warning. History must still render, so this never raises.
        """
        try:
            arn_to_brief = self._collect_briefs(service_name, since)
            if not arn_to_brief:
                return {}
            return self._resolve_states(arn_to_brief, family)
        except Exception:  # noqa: BLE001 - status is optional, never break history
            logger.warning(
                "state_by_revision failed for service %r since %s; "
                "history will render without rollout status",
                service_name,
                since.isoformat(),
                exc_info=True,
            )
            return {}

    def deployment_for_revision(
        self,
        service_name: str,
        revision: int,
        family: str,
        since: datetime | None = None,
    ) -> dict | None:
        """Return one service deployment's timestamps for the given task-def ``revision``.

        Maps ``{created_at, started_at, finished_at, status}`` for the most-recent deployment
        whose target service revision resolves to task-def ``revision`` in ``family``. Bounds
        the ``createdAt`` scan to ``since`` (default now-90d, ECS's retention window).

        Best-effort: ANY failure (unsupported boto3, AccessDenied, throttling, parse error) or
        no matching deployment returns ``None`` and logs a warning. The timeline must still
        render without ECS segments, so this never raises.
        """
        if since is None:
            since = datetime.now(UTC) - _DEFAULT_LOOKBACK
        try:
            arn_to_brief = self._collect_briefs(service_name, since)
            if not arn_to_brief:
                return None
            return self._brief_for_revision(arn_to_brief, revision, family)
        except Exception:  # noqa: BLE001 - ECS segments are optional, never break the timeline
            logger.warning(
                "deployment_for_revision failed for service %r revision %s since %s; "
                "timeline will render without ECS segments",
                service_name,
                revision,
                since.isoformat(),
                exc_info=True,
            )
            return None

    def _iter_briefs(self, service_name: str, since: datetime):
        """Yield every service-deployment brief created since ``since``, following nextToken.

        ``list_service_deployments`` has no botocore paginator in the installed boto3
        (``get_paginator`` raises ``OperationNotPageableError``), so page manually.
        """
        token: str | None = None
        while True:
            kwargs = {
                "cluster": self._cluster,
                "service": service_name,
                "createdAt": {"after": since},
            }
            if token:
                kwargs["nextToken"] = token
            resp = self._client.list_service_deployments(**kwargs)
            yield from resp.get("serviceDeployments", [])
            token = resp.get("nextToken")
            if not token:
                return

    def _collect_briefs(self, service_name: str, since: datetime) -> dict[str, dict]:
        """{targetServiceRevisionArn: newest brief} for deployments created since ``since``."""
        arn_to_brief: dict[str, dict] = {}
        for brief in self._iter_briefs(service_name, since):
            arn = brief.get("targetServiceRevisionArn")
            if not arn:
                continue
            existing = arn_to_brief.get(arn)
            if existing is None or _created(brief) >= _created(existing):
                arn_to_brief[arn] = brief  # keep newest deployment per target revision
        return arn_to_brief

    def _brief_for_revision(
        self, arn_to_brief: dict[str, dict], revision: int, family: str
    ) -> dict | None:
        """Find the brief whose service-revision arn resolves to task-def ``revision``."""
        arns = list(arn_to_brief)
        match: dict | None = None
        for start in range(0, len(arns), _DESCRIBE_BATCH):
            batch = arns[start : start + _DESCRIBE_BATCH]
            resp = self._client.describe_service_revisions(serviceRevisionArns=batch)
            for sr in resp.get("serviceRevisions", []):
                arn = sr.get("serviceRevisionArn")
                task_def = sr.get("taskDefinition")
                if not arn or not task_def:
                    continue
                if family and ECSDeployHistory.family_from_arn(task_def) != family:
                    continue
                if ECSDeployHistory._revision_from_arn(task_def) != revision:
                    continue
                brief = arn_to_brief.get(arn)
                if brief is None:
                    continue
                if match is None or _created(brief) >= _created(match):
                    match = brief  # newest matching deployment
        if match is None:
            return None
        return {
            "created_at": match.get("createdAt"),
            "started_at": match.get("startedAt"),
            "finished_at": match.get("finishedAt"),
            "status": match.get("status"),
        }

    def _resolve_states(
        self, arn_to_brief: dict[str, dict], family: str
    ) -> dict[int, dict]:
        """Resolve service-revision ARNs -> task-def revision int, keeping the NEWEST brief.

        ``arn_to_brief`` already holds the newest brief per service-revision ARN. When several
        ARNs map to the same task-def revision (e.g. a deploy then a rollback to the same image),
        the one with the latest ``createdAt`` wins so ``status`` reflects the most recent rollout.
        """
        result: dict[int, dict] = {}
        latest_created: dict[int, datetime] = {}
        arns = list(arn_to_brief)
        for start in range(0, len(arns), _DESCRIBE_BATCH):
            batch = arns[start : start + _DESCRIBE_BATCH]
            resp = self._client.describe_service_revisions(serviceRevisionArns=batch)
            for sr in resp.get("serviceRevisions", []):
                arn = sr.get("serviceRevisionArn")
                task_def = sr.get("taskDefinition")
                if not arn or not task_def:
                    continue
                if family and ECSDeployHistory.family_from_arn(task_def) != family:
                    continue  # guard against an unrelated family sharing the timeline
                revision = ECSDeployHistory._revision_from_arn(task_def)
                if revision is None:
                    continue
                brief = arn_to_brief[arn]
                created = _created(brief)
                existing = latest_created.get(revision)
                if existing is None or created >= existing:
                    latest_created[revision] = created
                    result[revision] = {
                        "finished_at": brief.get("finishedAt"),
                        "status": brief.get("status"),
                    }
        return result
