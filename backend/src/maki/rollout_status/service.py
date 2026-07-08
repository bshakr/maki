from datetime import UTC, datetime

from fastapi import HTTPException

from maki.schemas import RolloutDeployment, RolloutStatusResponse


class RolloutStatusService:
    """Live rollout view for one ECS service: PRIMARY (rolling out) vs ACTIVE (draining).

    Deliberately NOT cached (see rollout_status/routes.py for why): this exists to be polled at
    3-5s while a rollout is in progress, and any freshness window would defeat the point. One
    describe_services call for one service per request is cheap enough to just do it live
    every time.
    """

    def __init__(self, client, cluster: str, now=lambda: datetime.now(UTC)):
        self._client = client
        self._cluster = cluster
        self._now = now

    def get_rollout(self, name: str) -> RolloutStatusResponse:
        resp = self._client.describe_services(cluster=self._cluster, services=[name])
        services = resp.get("services", [])
        if not services:
            raise HTTPException(status_code=404, detail=f"Service '{name}' not found")
        deployments = [
            self._to_deployment(d) for d in self._sorted(services[0].get("deployments", []))
        ]
        return RolloutStatusResponse(
            service=name,
            deployments=deployments,
            in_progress=self._in_progress(deployments),
            generated_at=self._now(),
        )

    @staticmethod
    def _sorted(deployments: list[dict]) -> list[dict]:
        """PRIMARY first, then ACTIVE (draining), each group newest (createdAt) first."""

        def key(d: dict) -> tuple[int, float]:
            created = d.get("createdAt")
            ts = created.timestamp() if isinstance(created, datetime) else 0.0
            return (0 if d.get("status") == "PRIMARY" else 1, -ts)

        return sorted(deployments, key=key)

    @staticmethod
    def _to_deployment(d: dict) -> RolloutDeployment:
        return RolloutDeployment(
            status=d.get("status", "UNKNOWN"),
            rollout_state=d.get("rolloutState"),
            rollout_reason=d.get("rolloutStateReason"),
            desired_count=d.get("desiredCount"),
            running_count=d.get("runningCount"),
            pending_count=d.get("pendingCount"),
            failed_tasks=d.get("failedTasks"),
            task_definition=d.get("taskDefinition"),
            created_at=d.get("createdAt"),
            updated_at=d.get("updatedAt"),
        )

    @staticmethod
    def _in_progress(deployments: list[RolloutDeployment]) -> bool:
        primary = next((d for d in deployments if d.status == "PRIMARY"), None)
        if primary is not None and primary.rollout_state == "IN_PROGRESS":
            return True
        return any(
            d.status == "ACTIVE" and (d.running_count or 0) + (d.pending_count or 0) > 0
            for d in deployments
        )
