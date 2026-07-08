from maki.aws.images import sha_from_image, tag_from_image
from maki.schemas import DeployedService

_DESCRIBE_BATCH = 10


class ECSDeployRegistry:
    """Live, read-only view of currently-deployed ECS services in one cluster."""

    def __init__(self, client, cluster: str, region: str | None = None):
        self._client = client
        self._cluster = cluster
        self._region = region

    def list_deployed_services(self) -> list[DeployedService]:
        arns = self._list_service_arns()
        services, failures = self._describe_services(arns)
        # Caches the first container dict per task-def ARN: image + cpu/memory all come from
        # the one describe_task_definition call, so reservations add no extra AWS round-trip.
        cache: dict[str, dict | None] = {}
        result = [self._safe_map(svc, cache) for svc in services]
        result.extend(self._failure_row(f) for f in failures)
        return result

    def _list_service_arns(self) -> list[str]:
        arns: list[str] = []
        for page in self._client.get_paginator("list_services").paginate(cluster=self._cluster):
            arns.extend(page["serviceArns"])
        return arns

    def _describe_services(self, arns: list[str]) -> tuple[list[dict], list[dict]]:
        services: list[dict] = []
        failures: list[dict] = []
        for start in range(0, len(arns), _DESCRIBE_BATCH):
            batch = arns[start : start + _DESCRIBE_BATCH]
            if not batch:
                continue
            resp = self._client.describe_services(cluster=self._cluster, services=batch)
            services.extend(resp["services"])
            failures.extend(resp.get("failures", []))
        return services, failures

    def _safe_map(self, svc: dict, cache: dict[str, dict | None]) -> DeployedService:
        try:
            return self._to_deployed_service(svc, cache)
        except Exception as exc:  # one bad service must not sink the whole dashboard
            return DeployedService(
                name=svc.get("serviceName") or self._name_from_arn(svc.get("serviceArn", "")),
                platform="ecs",
                status=f"error: {type(exc).__name__}",
            )

    def _task_def(self, arn: str, cache: dict[str, dict | None]) -> dict | None:
        """The full task definition (image + cpu/memory), cached per ARN — one
        describe_task_definition call serves image and reservations alike."""
        if arn not in cache:
            cache[arn] = self._client.describe_task_definition(taskDefinition=arn)[
                "taskDefinition"
            ]
        return cache[arn]

    def _to_deployed_service(self, svc: dict, cache: dict[str, dict | None]) -> DeployedService:
        primary = self._primary_deployment(svc) or {}
        td_arn = primary.get("taskDefinition") or svc.get("taskDefinition")
        task_def = self._task_def(td_arn, cache) if td_arn else None
        containers = (task_def or {}).get("containerDefinitions") or []
        container = containers[0] if containers else None
        image = (container or {}).get("image")
        return DeployedService(
            name=svc["serviceName"],
            platform="ecs",
            git_sha=sha_from_image(image),
            image=image,
            version=tag_from_image(image),
            region=self._region,
            deployed_at=primary.get("updatedAt"),
            running_count=svc.get("runningCount"),
            desired_count=svc.get("desiredCount"),
            # pendingCount = tasks ECS is launching right now. It's our "actively
            # deploying" signal for services whose rolloutState is null (no
            # circuit-breaker rollout tracking) — see healthOf on the frontend.
            pending_count=primary.get("pendingCount"),
            status=primary.get("rolloutState"),
            rollout_reason=primary.get("rolloutStateReason"),
            rollout_progress=self._rollout_progress(
                svc.get("runningCount"), svc.get("desiredCount")
            ),
            # Reservations come free from the task def fetched above (no extra call).
            # Container-level wins; fall back to task-level, where Fargate (and
            # many EC2 task defs) actually declare cpu/memory as strings.
            cpu_reservation=self._reservation(
                (container or {}).get("cpu"), (task_def or {}).get("cpu")
            ),
            mem_reservation=self._reservation(
                (container or {}).get("memory"), (task_def or {}).get("memory")
            ),
        )

    @staticmethod
    def _reservation(container_val: object, task_val: object) -> int | None:
        """Container reservation wins; fall back to the task-level value (often a
        string like '256'). Returns None when neither is a parseable number."""
        for v in (container_val, task_val):
            if v is None:
                continue
            try:
                return int(v)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _rollout_progress(running: int | None, desired: int | None) -> float | None:
        if not desired:  # None or 0 — nothing to divide by
            return None
        return round(running / desired * 100, 1) if running is not None else None

    def _failure_row(self, failure: dict) -> DeployedService:
        return DeployedService(
            name=self._name_from_arn(failure.get("arn", "")),
            platform="ecs",
            status=f"unavailable: {failure.get('reason', 'unknown')}",
        )

    @staticmethod
    def _primary_deployment(svc: dict) -> dict | None:
        deployments = svc.get("deployments", [])
        for deployment in deployments:
            if deployment.get("status") == "PRIMARY":
                return deployment
        return deployments[0] if deployments else None

    @staticmethod
    def _name_from_arn(arn: str) -> str:
        return arn.rsplit("/", 1)[-1] or "unknown"
