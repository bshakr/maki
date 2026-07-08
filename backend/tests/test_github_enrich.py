from datetime import UTC, datetime
from unittest.mock import MagicMock

from maki.github_enrich import GitHubEnricher


def _resp(status, payload=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload or {}
    return r


def test_commit_returns_author_message_url():
    client = MagicMock()
    client.get.return_value = _resp(
        200,
        {
            "html_url": "https://github.com/acme/platform/commit/abc",
            "author": {
                "login": "bailey",
                "avatar_url": "https://avatars.githubusercontent.com/u/1?v=4",
            },
            "commit": {
                "author": {"name": "Bob Smith"},
                "message": "fix tax calc\n\ndetails...",
            },
        },
    )
    info = GitHubEnricher(token="t", client=client).commit("acme/platform", "abc")
    assert info.author == "bailey"
    assert info.author_avatar_url == "https://avatars.githubusercontent.com/u/1?v=4"
    assert info.message == "fix tax calc"
    assert info.commit_url == "https://github.com/acme/platform/commit/abc"


def test_author_avatar_url_none_when_top_level_author_null():
    client = MagicMock()
    client.get.return_value = _resp(
        200,
        {
            "html_url": "u",
            "author": None,
            "commit": {"author": {"name": "CI Bot"}, "message": "deploy"},
        },
    )
    info = GitHubEnricher(client=client).commit("o/r", "sha")
    assert info.author_avatar_url is None


def test_falls_back_to_commit_author_name_when_no_login():
    client = MagicMock()
    client.get.return_value = _resp(
        200,
        {
            "html_url": "u",
            "author": None,
            "commit": {"author": {"name": "CI Bot"}, "message": "deploy"},
        },
    )
    info = GitHubEnricher(client=client).commit("o/r", "sha")
    assert info.author == "CI Bot"


def test_non_200_returns_none():
    client = MagicMock()
    client.get.return_value = _resp(404)
    assert GitHubEnricher(client=client).commit("o/r", "missing") is None


def test_result_is_cached():
    client = MagicMock()
    client.get.return_value = _resp(200, {"html_url": "u", "commit": {"message": "m"}})
    enr = GitHubEnricher(client=client)
    enr.commit("o/r", "sha")
    enr.commit("o/r", "sha")
    assert client.get.call_count == 1


def test_pr_url_derived_from_commit_message():
    client = MagicMock()
    client.get.return_value = _resp(
        200,
        {
            "html_url": "https://github.com/acme/platform/commit/abc",
            "author": {"login": "bailey"},
            "commit": {
                "author": {"name": "Bob Smith"},
                "message": "Feat: [INS-2347] — anchor shifts (#7412)",
            },
        },
    )
    info = GitHubEnricher(client=client).commit("acme/platform", "abc")
    assert info.pr_url == "https://github.com/acme/platform/pull/7412"


def test_pr_url_none_when_no_number_in_message():
    client = MagicMock()
    client.get.return_value = _resp(
        200,
        {
            "html_url": "u",
            "author": {"login": "bailey"},
            "commit": {"author": {"name": "Bob Smith"}, "message": "plain message"},
        },
    )
    info = GitHubEnricher(client=client).commit("acme/platform", "abc")
    assert info.pr_url is None


def test_parses_committed_at_from_commit_committer_date():
    client = MagicMock()
    client.get.return_value = _resp(
        200,
        {
            "html_url": "u",
            "author": {"login": "bailey"},
            "commit": {
                "author": {"name": "Bob Smith"},
                "committer": {"date": "2026-05-30T09:15:00Z"},
                "message": "m",
            },
        },
    )
    info = GitHubEnricher(client=client).commit("o/r", "sha")
    assert info.committed_at == datetime(2026, 5, 30, 9, 15, tzinfo=UTC)


def test_committed_at_none_when_date_missing():
    client = MagicMock()
    client.get.return_value = _resp(
        200, {"html_url": "u", "commit": {"committer": {}, "message": "m"}}
    )
    info = GitHubEnricher(client=client).commit("o/r", "sha")
    assert info.committed_at is None


def test_committed_at_none_when_unparseable():
    client = MagicMock()
    client.get.return_value = _resp(
        200,
        {"html_url": "u", "commit": {"committer": {"date": "not-a-date"}, "message": "m"}},
    )
    info = GitHubEnricher(client=client).commit("o/r", "sha")
    assert info.committed_at is None


def test_token_sets_auth_header():
    client = MagicMock()
    client.get.return_value = _resp(200, {"html_url": "u", "commit": {"message": "m"}})
    GitHubEnricher(token="secret", client=client).commit("o/r", "sha")
    _, kwargs = client.get.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer secret"
