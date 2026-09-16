"""Unit tests for the ECS-status -> normalized feed-status mapping."""

import pytest

from maki.deploy_status import TERMINAL_STATUSES, normalize_status


@pytest.mark.parametrize(
    ("ecs_status", "expected"),
    [
        ("SUCCESSFUL", ("success", False)),
        ("IN_PROGRESS", ("in_progress", False)),
        ("PENDING", ("in_progress", False)),
        ("STOPPED", ("failed", False)),
        ("STOP_REQUESTED", ("failed", False)),
        ("ROLLBACK_SUCCESSFUL", ("success", True)),
        ("ROLLBACK_IN_PROGRESS", ("in_progress", True)),
        ("ROLLBACK_REQUESTED", ("in_progress", True)),
        ("ROLLBACK_FAILED", ("failed", True)),
        (None, (None, False)),
        ("", (None, False)),
        ("SOMETHING_NEW_FROM_AWS", (None, False)),
    ],
)
def test_normalize_status(ecs_status, expected):
    assert normalize_status(ecs_status) == expected


def test_terminal_statuses_exclude_in_progress():
    assert TERMINAL_STATUSES == frozenset({"success", "failed"})
