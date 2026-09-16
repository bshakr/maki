import logging
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class GitHubActions:
    """Look up GitHub Actions jobs for a commit sha. Token-optional, sha-cached, fail-soft.

    Mirrors ``GitHubEnricher``: same httpx + caching + defensive style. Any failure (no token
    is fine, but a network error, non-200, or parse error) degrades to ``[]`` and never raises,
    so a missing/rate-limited Actions API just drops the CI segments from the timeline.

    ``recent_failed_runs``/``jobs_for_run`` serve the watcher instead and are uncached — see their
    docstrings.
    """

    def __init__(
        self,
        token: str | None = None,
        base_url: str = "https://api.github.com",
        client: httpx.Client | None = None,
    ):
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=5.0)
        self._cache: dict[tuple[str, str], list[dict]] = {}
        self._full_sha_cache: dict[tuple[str, str], str] = {}

    def jobs_for_sha(self, repo: str, sha: str) -> list[dict]:
        """All Actions jobs across runs for ``sha`` as ``{name, started_at, completed_at,
        conclusion, run_id, html_url}`` dicts. ``run_id``/``html_url`` let callers keep only
        the deploy-producing run (and link to it) and drop jobs from unrelated runs
        (dependency upgrades, CodeQL). Empty list when repo/sha missing or anything fails."""
        if not repo or not sha:
            return []
        key = (repo, sha)
        if key in self._cache:
            return self._cache[key]
        jobs = self._fetch(repo, sha)
        self._cache[key] = jobs
        return jobs

    def recent_failed_runs(self, repo: str, since: datetime) -> list[dict]:
        """Failed workflow runs for ``repo`` created at or after ``since``, as
        ``{id, name, head_sha, html_url, created_at, updated_at}`` dicts.

        Deliberately uncached, unlike ``jobs_for_sha``: the watcher polls this every cycle, and a
        cached answer would latch onto the first result forever.
        """
        try:
            resp = self._client.get(
                f"{self._base_url}/repos/{repo}/actions/runs",
                params={"status": "failure", "per_page": 20},
                headers=self._headers(),
            )
            if resp.status_code != 200:
                logger.warning("recent_failed_runs for %s -> %s", repo, resp.status_code)
                return []
            runs: list[dict] = []
            for run in resp.json().get("workflow_runs", []):
                created = _parse_ts(run.get("created_at"))
                if created is None or created < since:
                    continue
                runs.append(
                    {
                        "id": run.get("id"),
                        "name": run.get("name"),
                        "head_sha": run.get("head_sha"),
                        "html_url": run.get("html_url"),
                        "created_at": created,
                        "updated_at": _parse_ts(run.get("updated_at")),
                    }
                )
            return runs
        except Exception:  # noqa: BLE001 - the watcher must survive a GitHub outage
            logger.warning("recent_failed_runs failed for %s", repo, exc_info=True)
            return []

    def jobs_for_run(self, repo: str, run_id: int) -> list[dict]:
        """Jobs of a single run as ``{name, conclusion, html_url}`` dicts. Uncached, for the same
        reason as ``recent_failed_runs``."""
        try:
            resp = self._client.get(
                f"{self._base_url}/repos/{repo}/actions/runs/{run_id}/jobs",
                params={"per_page": 100},
                headers=self._headers(),
            )
            if resp.status_code != 200:
                logger.warning("jobs_for_run %s run %s -> %s", repo, run_id, resp.status_code)
                return []
            return [
                {
                    "name": job.get("name"),
                    "conclusion": job.get("conclusion"),
                    "html_url": job.get("html_url"),
                }
                for job in resp.json().get("jobs", [])
            ]
        except Exception:  # noqa: BLE001 - the watcher must survive a GitHub outage
            logger.warning("jobs_for_run failed for %s run %s", repo, run_id, exc_info=True)
            return []

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _fetch(self, repo: str, sha: str) -> list[dict]:
        try:
            # actions/runs?head_sha= matches only the full 40-char sha; deploy image tags are
            # usually the short sha, so resolve it first or every CI lookup comes back empty.
            runs = self._runs(repo, self._full_sha(repo, sha))
            jobs: list[dict] = []
            for run in runs:
                jobs.extend(self._jobs_for_run(repo, run["id"], run.get("html_url")))
            return jobs
        except httpx.HTTPError:
            logger.warning("jobs_for_sha network error for %s@%s", repo, sha)
            return []
        except Exception:  # noqa: BLE001 - CI segments are optional, never break the timeline
            logger.warning("jobs_for_sha failed for %s@%s", repo, sha, exc_info=True)
            return []

    def _full_sha(self, repo: str, sha: str) -> str:
        """Resolve a short sha to its full 40-char form via the commits API; pass through a sha
        already full. Fail-soft: on any non-200 / missing field, return the input unchanged (the
        runs query then yields no matches, same as before)."""
        if len(sha) >= 40:
            return sha
        cached = self._full_sha_cache.get((repo, sha))
        if cached is not None:
            return cached
        resp = self._client.get(
            f"{self._base_url}/repos/{repo}/commits/{sha}", headers=self._headers()
        )
        full = resp.json().get("sha", sha) if resp.status_code == 200 else sha
        self._full_sha_cache[(repo, sha)] = full
        return full

    def _runs(self, repo: str, sha: str) -> list[dict]:
        url = f"{self._base_url}/repos/{repo}/actions/runs"
        resp = self._client.get(url, params={"head_sha": sha}, headers=self._headers())
        if resp.status_code != 200:
            return []
        data = resp.json()
        runs: list[dict] = []
        for run in data.get("workflow_runs", []):
            run_id = run.get("id")
            if isinstance(run_id, int):
                runs.append({"id": run_id, "html_url": run.get("html_url")})
        return runs

    def _jobs_for_run(self, repo: str, run_id: int, html_url: str | None = None) -> list[dict]:
        url = f"{self._base_url}/repos/{repo}/actions/runs/{run_id}/jobs"
        resp = self._client.get(url, headers=self._headers())
        if resp.status_code != 200:
            return []
        data = resp.json()
        jobs: list[dict] = []
        for job in data.get("jobs", []):
            jobs.append(
                {
                    "name": job.get("name"),
                    "started_at": job.get("started_at"),
                    "completed_at": job.get("completed_at"),
                    "conclusion": job.get("conclusion"),
                    "run_id": run_id,
                    "html_url": html_url,
                }
            )
        return jobs
