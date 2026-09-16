"""The one mapping from a raw ECS service-deployment status to maki's normalized feed state.

Shared by the deploy-events ingester and the watcher so both agree on what "failed" means.
"""

# The four derivable feed states are in_progress / success / failed (or None when unknown), with
# is_rollback flagging the rollback variants so a rollback renders distinctly from a forward deploy.
_MAPPING: dict[str, tuple[str | None, bool]] = {
    "SUCCESSFUL": ("success", False),
    "IN_PROGRESS": ("in_progress", False),
    "PENDING": ("in_progress", False),
    "STOPPED": ("failed", False),
    "STOP_REQUESTED": ("failed", False),
    "ROLLBACK_SUCCESSFUL": ("success", True),
    "ROLLBACK_IN_PROGRESS": ("in_progress", True),
    "ROLLBACK_REQUESTED": ("in_progress", True),
    "ROLLBACK_FAILED": ("failed", True),
}

TERMINAL_STATUSES = frozenset({"success", "failed"})


def normalize_status(ecs_status: str | None) -> tuple[str | None, bool]:
    """Map a raw ECS service-deployment status to ``(normalized_status, is_rollback)``."""
    return _MAPPING.get(ecs_status or "", (None, False))
