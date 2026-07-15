from subprocess import CompletedProcess, TimeoutExpired
from unittest.mock import patch

from maki.version.service import check_version

HEAD = ("rev-parse", "HEAD")
UPSTREAM = ("rev-parse", "--abbrev-ref", "@{upstream}")
LS_REMOTE = ("ls-remote", "origin", "refs/heads/main")
IS_ANCESTOR = ("merge-base", "--is-ancestor", "bbb", "HEAD")
COUNT = ("rev-list", "--count", "HEAD..bbb")

FAIL = (128, "")


def fake_git(responses):
    """subprocess.run stand-in keyed on the git arg tuple; unknown commands fail like git."""

    def run(cmd, **kwargs):
        rc, out = responses.get(tuple(cmd[1:]), FAIL)
        if rc is TimeoutExpired:
            raise TimeoutExpired(cmd, 3.0)
        return CompletedProcess(cmd, rc, stdout=out, stderr="")

    return run


def check_with(responses):
    with patch("maki.version.service.subprocess.run", side_effect=fake_git(responses)):
        return check_version()


def test_behind_reports_update_with_count():
    status = check_with(
        {
            HEAD: (0, "aaa\n"),
            UPSTREAM: (0, "origin/main\n"),
            LS_REMOTE: (0, "bbb\trefs/heads/main\n"),
            IS_ANCESTOR: (1, ""),
            COUNT: (0, "4\n"),
        }
    )
    assert status.update_available is True
    assert status.behind_by == 4
    assert status.current_sha == "aaa"
    assert status.upstream == "origin/main"


def test_up_to_date_when_remote_tip_matches_head():
    status = check_with(
        {
            HEAD: (0, "aaa\n"),
            UPSTREAM: (0, "origin/main\n"),
            LS_REMOTE: (0, "aaa\trefs/heads/main\n"),
        }
    )
    assert status.update_available is False
    assert status.current_sha == "aaa"


def test_local_ahead_is_not_behind():
    # Remote tip is an ancestor of HEAD → we have everything the remote has.
    status = check_with(
        {
            HEAD: (0, "aaa\n"),
            UPSTREAM: (0, "origin/main\n"),
            LS_REMOTE: (0, "bbb\trefs/heads/main\n"),
            IS_ANCESTOR: (0, ""),
        }
    )
    assert status.update_available is False


def test_unknown_remote_object_reports_update_without_count():
    # ls-remote doesn't fetch: a never-seen remote sha fails merge-base and rev-list.
    status = check_with(
        {
            HEAD: (0, "aaa\n"),
            UPSTREAM: (0, "origin/main\n"),
            LS_REMOTE: (0, "bbb\trefs/heads/main\n"),
            IS_ANCESTOR: FAIL,
            COUNT: FAIL,
        }
    )
    assert status.update_available is True
    assert status.behind_by is None


def test_offline_ls_remote_failure_is_silent():
    status = check_with(
        {
            HEAD: (0, "aaa\n"),
            UPSTREAM: (0, "origin/main\n"),
            LS_REMOTE: FAIL,
        }
    )
    assert status.update_available is False


def test_ls_remote_timeout_is_silent():
    status = check_with(
        {
            HEAD: (0, "aaa\n"),
            UPSTREAM: (0, "origin/main\n"),
            LS_REMOTE: (TimeoutExpired, ""),
        }
    )
    assert status.update_available is False


def test_not_a_git_repo_is_silent():
    status = check_with({})
    assert status.update_available is False
    assert status.current_sha is None


def test_no_upstream_is_silent():
    status = check_with({HEAD: (0, "aaa\n")})
    assert status.update_available is False
    assert status.current_sha == "aaa"
