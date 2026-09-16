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
    half ('deploy-insights / deploy', 'build / insights deploy'), so every segment is tried.

    What remains once the deploy marker is stripped must be the service itself or a
    separator-bounded tail of it: CI job names drop the env/domain prefix the ECS names carry, so
    'deploy-timecard-sync' rolls out 'prod-workforce-payroll-timecard-sync'. The separator
    boundary is what keeps that from bleeding across siblings — 'deploy-insights-worker' is the
    worker's rollout, not insights'.
    """
    target = service.strip().lower()
    if not target:
        return False
    prefixes = [p.lower() for p in prefixes]
    suffixes = [s.lower() for s in suffixes]
    return any(
        target == token or target.endswith(f"-{token}")
        for segment in job_name.lower().split(" / ")
        for token in _deploy_tokens(segment.strip(), prefixes, suffixes)
    )


def _deploy_tokens(segment: str, prefixes: Sequence[str], suffixes: Sequence[str]) -> list[str]:
    """Every service token a deploy-shaped job name segment could be naming.

    All markers are tried, not just the first that fits: with prefixes ``["deploy-",
    "deploy-prod-"]`` the segment 'deploy-prod-inventory' yields both 'prod-inventory' and
    'inventory', so a match no longer depends on how the config lists them.
    """
    tokens = []
    for prefix in prefixes:
        if segment.startswith(prefix):
            tokens.append(segment[len(prefix) :].strip(_TRIM))
    for suffix in suffixes:
        if segment.endswith(suffix):
            tokens.append(segment[: -len(suffix)].strip(_TRIM))
    return [t for t in tokens if t]
