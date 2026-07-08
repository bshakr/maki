from unittest.mock import MagicMock

import httpx

from maki.github_actions import GitHubActions


def _resp(status, payload=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload or {}
    return r


def _client_for(runs_payload, jobs_by_run):
    client = MagicMock()

    def get(url, params=None, headers=None):
        if url.endswith("/actions/runs"):
            return _resp(200, runs_payload)
        for run_id, jobs in jobs_by_run.items():
            if url.endswith(f"/actions/runs/{run_id}/jobs"):
                return _resp(200, {"jobs": jobs})
        return _resp(404)

    client.get.side_effect = get
    return client


def test_flattens_jobs_across_runs():
    runs = {"workflow_runs": [{"id": 11}, {"id": 22}]}
    jobs = {
        11: [
            {
                "name": "Build",
                "started_at": "2026-05-29T04:00:38Z",
                "completed_at": "2026-05-29T04:01:16Z",
                "conclusion": "success",
            }
        ],
        22: [
            {
                "name": "Test",
                "started_at": "2026-05-29T04:01:20Z",
                "completed_at": "2026-05-29T04:02:32Z",
                "conclusion": "success",
            }
        ],
    }
    actions = GitHubActions(token="t", client=_client_for(runs, jobs))
    out = actions.jobs_for_sha("acme/platform", "abc")
    assert [j["name"] for j in out] == ["Build", "Test"]
    assert out[0]["started_at"] == "2026-05-29T04:00:38Z"
    assert out[0]["conclusion"] == "success"
    # Each job carries its originating run id so the timeline can keep only the
    # deploy-producing run and drop unrelated runs on the same sha.
    assert out[0]["run_id"] == 11
    assert out[1]["run_id"] == 22


def test_run_html_url_is_attached_to_each_of_its_jobs():
    runs = {
        "workflow_runs": [
            {"id": 11, "html_url": "https://github.com/acme/platform/actions/runs/11"},
            {"id": 22, "html_url": "https://github.com/acme/platform/actions/runs/22"},
        ]
    }
    jobs = {
        11: [{"name": "Build", "conclusion": "success"}],
        22: [{"name": "Test", "conclusion": "success"}],
    }
    actions = GitHubActions(token="t", client=_client_for(runs, jobs))
    out = actions.jobs_for_sha("acme/platform", "abc")
    assert out[0]["html_url"] == "https://github.com/acme/platform/actions/runs/11"
    assert out[1]["html_url"] == "https://github.com/acme/platform/actions/runs/22"


def test_empty_when_no_runs_for_sha():
    out = GitHubActions(client=_client_for({"workflow_runs": []}, {})).jobs_for_sha("o/r", "sha")
    assert out == []


def test_empty_and_no_call_when_repo_or_sha_missing():
    client = MagicMock()
    assert GitHubActions(client=client).jobs_for_sha("", "sha") == []
    assert GitHubActions(client=client).jobs_for_sha("o/r", "") == []
    client.get.assert_not_called()


def test_non_200_runs_returns_empty():
    client = MagicMock()
    client.get.return_value = _resp(403)
    assert GitHubActions(client=client).jobs_for_sha("o/r", "sha") == []


def test_network_error_returns_empty():
    client = MagicMock()
    client.get.side_effect = httpx.ConnectError("boom")
    assert GitHubActions(client=client).jobs_for_sha("o/r", "sha") == []


def test_result_is_cached():
    runs = {"workflow_runs": [{"id": 11}]}
    jobs = {11: [{"name": "Build", "conclusion": "success"}]}
    client = _client_for(runs, jobs)
    actions = GitHubActions(client=client)
    full = "a" * 40  # already-full sha -> no commit-resolution call to muddy the count
    actions.jobs_for_sha("o/r", full)
    actions.jobs_for_sha("o/r", full)
    # runs endpoint + jobs endpoint hit once total, not twice
    assert client.get.call_count == 2


def test_short_sha_resolved_to_full_before_querying_runs():
    # actions/runs?head_sha= matches only the full sha, so a short image-tag sha must be
    # resolved via the commits API first or CI segments come back empty (the timeline regression).
    full = "8759788e642788f464cfed7ad5ca66271656f10e"
    queried = {}

    def get(url, params=None, headers=None):
        if url.endswith("/commits/8759788"):
            return _resp(200, {"sha": full})
        if url.endswith("/actions/runs"):
            queried["head_sha"] = params["head_sha"]
            return _resp(200, {"workflow_runs": [{"id": 11}]})
        if url.endswith("/actions/runs/11/jobs"):
            return _resp(200, {"jobs": [{"name": "Test", "conclusion": "success"}]})
        return _resp(404)

    client = MagicMock()
    client.get.side_effect = get
    out = GitHubActions(token="t", client=client).jobs_for_sha("acme/platform", "8759788")

    assert queried["head_sha"] == full  # runs queried with the resolved full sha
    assert [j["name"] for j in out] == ["Test"]


def test_short_sha_resolution_failure_falls_back_softly():
    # If the commit lookup fails (404/rate-limit), fall back to the input sha — no crash,
    # just the same empty-ish result as before (runs query won't match, returns []).
    client = MagicMock()
    client.get.return_value = _resp(404)
    assert GitHubActions(client=client).jobs_for_sha("o/r", "deadbee") == []


def test_token_sets_auth_header():
    client = _client_for({"workflow_runs": []}, {})
    GitHubActions(token="secret", client=client).jobs_for_sha("o/r", "sha")
    _, kwargs = client.get.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer secret"


def test_no_token_omits_auth_header():
    client = _client_for({"workflow_runs": []}, {})
    GitHubActions(client=client).jobs_for_sha("o/r", "sha")
    _, kwargs = client.get.call_args
    assert "Authorization" not in kwargs["headers"]
