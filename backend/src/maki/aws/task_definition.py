import logging

logger = logging.getLogger(__name__)


class ECSTaskDefinition:
    """Read-only view of a service's CURRENT task-definition env + secret references.

    Surfaces plain environment variables (name + value) and secret references (name +
    ``valueFrom`` ARN) — NEVER a secret value. ``describe_task_definition`` returns only the
    reference for a secret, so no value ever flows through here and SSM/Secrets Manager are
    never touched. Fail-soft like the other AWS wrappers: any error degrades to ``None``.
    """

    def __init__(self, client, cluster: str):
        self._client = client
        self._cluster = cluster

    def current_env(self, service_name: str) -> dict | None:
        """Env + secret refs for the service's current task def, or None if unresolvable.

        Shape: ``{"task_def": "<family:rev>", "containers": [{"name", "environment":
        [{"name","value"}], "secrets": [{"name","value_from"}]}]}``.
        """
        try:
            arn = self._current_task_def_arn(service_name)
            if not arn:
                return None
            td = self._client.describe_task_definition(taskDefinition=arn)["taskDefinition"]
            containers = [
                self._container_env(container) for container in td.get("containerDefinitions", [])
            ]
            return {"task_def": self._task_def_from_arn(arn), "containers": containers}
        except Exception:  # noqa: BLE001 - env view is read-only and optional; never raise
            logger.warning("current_env failed for %r", service_name, exc_info=True)
            return None

    def log_group(self, service_name: str) -> tuple[str, str | None] | None:
        """Resolve the real CloudWatch log group for a service from its current task def.

        Reads the container's ``logConfiguration`` (logDriver ``awslogs``) and returns
        ``(awslogs-group, awslogs-region)``. The ``/ecs/<service>-production`` naming convention
        doesn't hold for many services, so the authoritative group lives on the task def.

        Container selection: prefer the container whose name matches ``service_name`` (when it has
        an awslogs group); otherwise the first container that has one.

        Fail-soft: returns ``None`` if there's no task def / no awslogs config / any AWS error, so
        callers fall back to the ``/ecs/<service>-production`` convention and never regress.
        """
        try:
            arn = self._current_task_def_arn(service_name)
            if not arn:
                return None
            td = self._client.describe_task_definition(taskDefinition=arn)["taskDefinition"]
            containers = td.get("containerDefinitions", [])
            chosen = self._choose_log_container(containers, service_name)
            if chosen is None:
                return None
            options = chosen.get("logConfiguration", {}).get("options", {}) or {}
            group = options.get("awslogs-group")
            if not group:
                return None
            return group, options.get("awslogs-region")
        except Exception:  # noqa: BLE001 - resolution is best-effort; callers fall back on None
            logger.warning("log_group resolution failed for %r", service_name, exc_info=True)
            return None

    @staticmethod
    def _choose_log_container(containers: list[dict], service_name: str) -> dict | None:
        """Pick the container carrying the awslogs group: name match first, else first available."""
        with_awslogs = [
            c
            for c in containers
            if c.get("logConfiguration", {}).get("logDriver") == "awslogs"
            and (c.get("logConfiguration", {}).get("options") or {}).get("awslogs-group")
        ]
        if not with_awslogs:
            return None
        for container in with_awslogs:
            if container.get("name") == service_name:
                return container
        return with_awslogs[0]

    def _current_task_def_arn(self, service_name: str) -> str | None:
        resp = self._client.describe_services(cluster=self._cluster, services=[service_name])
        services = resp.get("services", [])
        if not services:
            return None
        return services[0].get("taskDefinition")

    @staticmethod
    def _container_env(container: dict) -> dict:
        environment = [
            {"name": e.get("name"), "value": e.get("value")}
            for e in container.get("environment", [])
        ]
        # Echo ONLY the reference (valueFrom); a secret's value is never present here.
        secrets = [
            {"name": s.get("name"), "value_from": s.get("valueFrom")}
            for s in container.get("secrets", [])
        ]
        return {
            "name": container.get("name"),
            "environment": environment,
            "secrets": secrets,
        }

    @staticmethod
    def _task_def_from_arn(arn: str) -> str | None:
        """'arn:...:task-definition/inventory:42' -> 'inventory:42'."""
        if "task-definition/" not in arn:
            return None
        return arn.split("task-definition/", 1)[1] or None
