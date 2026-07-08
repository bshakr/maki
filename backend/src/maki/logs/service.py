from maki.aws.logs import LogTail, LogTailResult
from maki.aws.task_definition import ECSTaskDefinition
from maki.cache import SwrCache
from maki.schemas import LogEventItem, ServiceLogsResponse


def log_group_for(service_name: str) -> str:
    """Fallback ECS log group for a service, matching the console deep-link convention.

    Used only when the real group can't be resolved from the task def (no task def / no awslogs
    config / AWS error). The convention is ``/ecs/<service>-production`` (see the frontend's
    ``cloudWatchLogsUrl``); the authoritative group is the task def's container
    ``logConfiguration.options["awslogs-group"]`` (resolved by ``ECSTaskDefinition.log_group``).
    """
    return f"/ecs/{service_name}-production"


class ServiceLogsService:
    """In-app CloudWatch Logs tail for one service, briefly SWR-cached over the live reads.

    The cache window is short (a few seconds) so the viewer feels live while a burst of refreshes
    (or the auto-refresh poll) doesn't fan out one FilterLogEvents call per request. A manual
    ``force`` (``?refresh=1``) bypasses the cache for an explicit "show me now".
    """

    def __init__(
        self,
        tail: LogTail,
        task_def: ECSTaskDefinition,
        region: str,
        fresh_seconds: float,
        stale_seconds: float,
    ):
        self._tail = tail
        self._task_def = task_def
        self._region = region
        self._cache = SwrCache(fresh_seconds, stale_seconds)

    def get_logs(
        self, service_name: str, limit: int, since_minutes: int, force: bool = False
    ) -> ServiceLogsResponse:
        return self._cache.get(
            (service_name, limit, since_minutes),
            lambda: self._compute(service_name, limit, since_minutes),
            force=force,
        )

    def _compute(self, service_name: str, limit: int, since_minutes: int) -> ServiceLogsResponse:
        # Resolve the authoritative group from the task def; fall back to the naming convention so
        # behaviour never regresses. This lands inside the SWR-cached compute, so it's not
        # re-fetched on every poll. Prefer the task def's awslogs-region, else the configured one.
        resolved = self._task_def.log_group(service_name)
        if resolved is not None:
            log_group, td_region = resolved
            region = td_region or self._region
        else:
            log_group = log_group_for(service_name)
            region = self._region
        result: LogTailResult = self._tail.tail(log_group, limit=limit, since_minutes=since_minutes)
        return ServiceLogsResponse(
            log_group=log_group,
            region=region,
            events=[
                LogEventItem(timestamp=e.timestamp, message=e.message, stream=e.stream)
                for e in result.events
            ],
            truncated=result.truncated,
            error=result.error,
        )
