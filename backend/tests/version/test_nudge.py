from unittest.mock import patch

from maki.schemas import VersionResponse
from maki.version import nudge


def run_nudge(capsys, fake: VersionResponse) -> str:
    with patch("maki.version.nudge.check_version", return_value=fake):
        nudge.main()
    return capsys.readouterr().out


def test_silent_when_up_to_date(capsys):
    assert run_nudge(capsys, VersionResponse(current_sha="aaa")) == ""


def test_silent_when_check_could_not_run(capsys):
    assert run_nudge(capsys, VersionResponse()) == ""


def test_prints_count_and_upstream_when_behind(capsys):
    out = run_nudge(
        capsys,
        VersionResponse(
            current_sha="aaa", upstream="origin/main", behind_by=4, update_available=True
        ),
    )
    assert "4 commits behind origin/main" in out
    assert "make update" in out


def test_singular_commit(capsys):
    out = run_nudge(
        capsys,
        VersionResponse(
            current_sha="aaa", upstream="origin/main", behind_by=1, update_available=True
        ),
    )
    assert "1 commit behind origin/main" in out


def test_countless_update_still_nudges(capsys):
    out = run_nudge(
        capsys,
        VersionResponse(current_sha="aaa", upstream="origin/main", update_available=True),
    )
    assert "behind origin/main" in out
    assert "make update" in out
