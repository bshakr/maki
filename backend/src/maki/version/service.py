import os
import subprocess

from maki.cache import SwrCache
from maki.schemas import VersionResponse

GIT_TIMEOUT_SECONDS = 3.0


def _git(*args: str) -> str | None:
    """Run a git command; None on any failure (not a repo, offline, timeout, non-zero exit)."""
    try:
        # Never let git block on a credential/auth prompt — a check must be fire-and-forget.
        out = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def check_version() -> VersionResponse:
    """Compare local HEAD with the upstream branch tip on the remote, without fetching.

    ls-remote is a single read-only network call; "behind" means the remote tip isn't an
    ancestor of HEAD. Every failure degrades to update_available=False — the nudge must
    never invent staleness.
    """
    head = _git("rev-parse", "HEAD")
    if head is None:
        return VersionResponse()
    upstream = _git("rev-parse", "--abbrev-ref", "@{upstream}")
    if upstream is None or "/" not in upstream:
        return VersionResponse(current_sha=head)
    remote, _, branch = upstream.partition("/")
    listed = _git("ls-remote", remote, f"refs/heads/{branch}")
    if not listed:
        return VersionResponse(current_sha=head, upstream=upstream)
    remote_sha = listed.split()[0]
    if remote_sha == head:
        return VersionResponse(current_sha=head, upstream=upstream)
    # Remote tip that's an ancestor of HEAD means we're ahead, not behind. A never-fetched
    # remote sha fails merge-base (and rev-list below) — then we know only that the remote
    # moved: report an update without a count.
    if _git("merge-base", "--is-ancestor", remote_sha, "HEAD") is not None:
        return VersionResponse(current_sha=head, upstream=upstream)
    count = _git("rev-list", "--count", f"HEAD..{remote_sha}")
    behind = int(count) if count and count.isdigit() else None
    return VersionResponse(
        current_sha=head, upstream=upstream, behind_by=behind, update_available=True
    )


class VersionService:
    """Clone-freshness check, cached so a long dev session re-hits the remote hourly at most.

    The SPA can poll freely; only the first read past the fresh window pays the ls-remote call.
    """

    def __init__(self, fresh_seconds: float, stale_seconds: float):
        self._cache = SwrCache(fresh_seconds, stale_seconds)

    def get_version(self, force: bool = False) -> VersionResponse:
        return self._cache.get("version", check_version, force=force)
