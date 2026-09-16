"""Identify the CI job that deploys one particular service.

A repo maps to several services, so a run-level failure says nothing about which service broke.
The per-service rollout jobs are already described in config by
``deployTimeline.github.hideJobsStartingWith`` / ``hideJobsEndingWith`` — the same convention is
reused here to tell a deploy job apart from a test job.
"""

from collections.abc import Sequence

_TRIM = " -_/"


def is_deploy_job_for(
    job_name: str, service: str, prefixes: Sequence[str], suffixes: Sequence[str]
) -> bool:
    """Whether ``job_name`` is the job that rolls ``service`` out.

    GitHub renders reusable-workflow jobs as "caller / callee" and the service can sit in either
    half ('deploy-insights / deploy', 'build / insights deploy'), so every segment is tried. The
    service name must be what remains once the deploy marker is stripped, not merely a substring
    of it — 'deploy-insights-worker' is the worker's rollout, not insights'.
    """
    target = service.strip().lower()
    if not target:
        return False
    prefixes = [p.lower() for p in prefixes]
    suffixes = [s.lower() for s in suffixes]
    return any(
        _deploy_target(segment.strip(), prefixes, suffixes) == target
        for segment in job_name.lower().split(" / ")
    )


def _deploy_target(segment: str, prefixes: Sequence[str], suffixes: Sequence[str]) -> str | None:
    """The service a deploy-shaped job name segment targets, or ``None`` if it names none."""
    for prefix in prefixes:
        if segment.startswith(prefix):
            return segment[len(prefix) :].strip(_TRIM) or None
    for suffix in suffixes:
        if segment.endswith(suffix):
            return segment[: -len(suffix)].strip(_TRIM) or None
    return None
