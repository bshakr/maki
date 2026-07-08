import re
from datetime import datetime

import httpx

from maki.schemas import CommitInfo

_PR_RE = re.compile(r"#(\d+)")


def _parse_iso(value: object) -> datetime | None:
    """Parse a GitHub ISO-8601 timestamp (e.g. '2026-05-30T09:15:00Z'); None if absent/invalid."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class GitHubEnricher:
    """Look up commit metadata from the GitHub REST API. Token-optional, cached, fail-soft."""

    def __init__(
        self,
        token: str | None = None,
        base_url: str = "https://api.github.com",
        client: httpx.Client | None = None,
    ):
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=5.0)
        self._cache: dict[tuple[str, str], CommitInfo | None] = {}
        self._pull_cache: dict[tuple[str, int], dict | None] = {}

    def commit(self, repo: str | None, sha: str) -> CommitInfo | None:
        if not repo or not sha:
            return None
        key = (repo, sha)
        if key in self._cache:
            return self._cache[key]
        info = self._fetch(repo, sha)
        self._cache[key] = info
        return info

    def pull(self, repo: str | None, number: int) -> dict | None:
        """Fetch ``{title, body}`` for a PR via ``GET /repos/{repo}/pulls/{n}``.

        Token-optional, cached per ``(repo, number)``, fail-soft: no token / 404 / any error
        returns ``None`` and never raises, so a missing PR just drops the description.
        """
        if not repo or number is None:
            return None
        key = (repo, number)
        if key in self._pull_cache:
            return self._pull_cache[key]
        info = self._fetch_pull(repo, number)
        self._pull_cache[key] = info
        return info

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _base_url_html(self, repo: str) -> str:
        # PR links are always github.com web URLs, never the api.github.com base.
        return f"https://github.com/{repo}"

    def _fetch(self, repo: str, sha: str) -> CommitInfo | None:
        url = f"{self._base_url}/repos/{repo}/commits/{sha}"
        try:
            resp = self._client.get(url, headers=self._headers())
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        data = resp.json()
        commit = data.get("commit", {})
        author_obj = data.get("author") or {}
        commit_author = commit.get("author") or {}
        author = author_obj.get("login") or commit_author.get("name")
        author_avatar_url = author_obj.get("avatar_url")
        full_message = commit.get("message") or ""
        message = full_message.split("\n", 1)[0] or None
        pr_url = None
        m = _PR_RE.search(full_message)
        if m and repo:
            pr_url = f"{self._base_url_html(repo)}/pull/{m.group(1)}"
        committer = commit.get("committer") or {}
        return CommitInfo(
            author=author,
            author_avatar_url=author_avatar_url,
            message=message,
            commit_url=data.get("html_url"),
            pr_url=pr_url,
            committed_at=_parse_iso(committer.get("date")),
        )

    def _fetch_pull(self, repo: str, number: int) -> dict | None:
        url = f"{self._base_url}/repos/{repo}/pulls/{number}"
        try:
            resp = self._client.get(url, headers=self._headers())
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001 - PR description is optional, never raise
            return None
        return {"title": data.get("title"), "body": data.get("body")}
