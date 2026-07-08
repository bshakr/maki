from collections.abc import Callable
from datetime import UTC, datetime

from maki.aws.task_definition import ECSTaskDefinition
from maki.schemas import ContainerEnv, EnvVar, SecretRef, ServiceEnvResponse


class ServiceEnvService:
    """Current-task-def env + secret refs for one service, fetched fresh per request.

    Deliberately NOT cached: env values can be plaintext secrets, so we never retain them in
    process memory (the SwrCache has no eviction — a cached value would live for the whole
    process). Each call hits ECS describe_task_definition directly (one cheap read) and the
    response is held only for the lifetime of the request. Values are never written to the DB
    or logged.

    When the AWS wrapper can't resolve the service/task def it returns ``None``; we map that to
    a valid empty response (``task_def=None``, no containers) rather than raising — a missing
    env view should never error the page.
    """

    def __init__(
        self,
        task_def: ECSTaskDefinition,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._task_def = task_def
        self._now = now

    def get_env(self, service_name: str) -> ServiceEnvResponse:
        return self._compute(service_name)

    def _compute(self, service_name: str) -> ServiceEnvResponse:
        raw = self._task_def.current_env(service_name)
        if raw is None:
            return ServiceEnvResponse(
                service=service_name,
                task_def=None,
                containers=[],
                generated_at=self._now(),
            )
        containers = [
            ContainerEnv(
                name=container["name"],
                environment=[
                    EnvVar(name=e["name"], value=e["value"]) for e in container["environment"]
                ],
                secrets=[
                    SecretRef(name=s["name"], value_from=s["value_from"])
                    for s in container["secrets"]
                ],
            )
            for container in raw["containers"]
        ]
        return ServiceEnvResponse(
            service=service_name,
            task_def=raw["task_def"],
            containers=containers,
            generated_at=self._now(),
        )
