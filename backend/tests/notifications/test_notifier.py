import logging
from subprocess import CompletedProcess
from unittest.mock import MagicMock

from maki.notifications.notifier import MacNotifier, NullNotifier, build_notifier


def _runner(returncode: int = 0, stderr: str = ""):
    return MagicMock(return_value=CompletedProcess(args=[], returncode=returncode, stderr=stderr))


def test_prefers_terminal_notifier_when_present():
    runner = _runner()
    notifier = MacNotifier(runner=runner, which=lambda _: "/opt/homebrew/bin/terminal-notifier")

    notifier.notify(title="insights deployed", subtitle="abc1234", body="fix thing", url="http://x")

    argv = runner.call_args.args[0]
    assert argv[0] == "/opt/homebrew/bin/terminal-notifier"
    assert "-title" in argv and "insights deployed" in argv
    assert "-subtitle" in argv and "abc1234" in argv
    assert "-message" in argv and "fix thing" in argv
    assert "-open" in argv and "http://x" in argv
    assert runner.call_args.kwargs["timeout"] == 5
    assert runner.call_args.kwargs["check"] is False


def test_falls_back_to_osascript():
    runner = _runner()
    notifier = MacNotifier(runner=runner, which=lambda _: None)

    notifier.notify(title="t", subtitle="s", body="b", url=None)

    argv = runner.call_args.args[0]
    assert argv[0] == "osascript"
    assert argv[1] == "-e"
    assert argv[2] == 'display notification "b" with title "t" subtitle "s"'


def test_osascript_escapes_quotes_and_backslashes():
    runner = _runner()
    notifier = MacNotifier(runner=runner, which=lambda _: None)

    notifier.notify(title="t", subtitle=None, body='say "hi" \\ bye', url=None)

    script = runner.call_args.args[0][2]
    assert script == 'display notification "say \\"hi\\" \\\\ bye" with title "t"'


def test_osascript_flattens_newlines_that_would_end_the_literal():
    runner = _runner()
    notifier = MacNotifier(runner=runner, which=lambda _: None)

    notifier.notify(title="t", subtitle=None, body="first\r\nsecond", url=None)

    script = runner.call_args.args[0][2]
    assert script == 'display notification "first  second" with title "t"'


def test_logs_a_delivered_notification(caplog):
    with caplog.at_level(logging.INFO, logger="maki.notifications.notifier"):
        MacNotifier(runner=_runner(), which=lambda _: None).notify(
            title="insights deployed", subtitle=None, body="fix thing", url=None
        )

    assert "insights deployed" in caplog.text and "fix thing" in caplog.text


def test_a_non_zero_exit_warns_with_the_captured_stderr(caplog):
    runner = _runner(returncode=1, stderr="Not authorized to send Apple events")

    with caplog.at_level(logging.WARNING, logger="maki.notifications.notifier"):
        MacNotifier(runner=runner, which=lambda _: None).notify(
            title="t", subtitle=None, body="b", url=None
        )

    assert "Not authorized to send Apple events" in caplog.text


def test_never_uses_a_shell():
    runner = _runner()
    MacNotifier(runner=runner, which=lambda _: None).notify(
        title="t", subtitle=None, body="b", url=None
    )
    assert "shell" not in runner.call_args.kwargs


def test_subprocess_failure_is_swallowed():
    runner = MagicMock(side_effect=OSError("boom"))
    MacNotifier(runner=runner, which=lambda _: None).notify(
        title="t", subtitle=None, body="b", url=None
    )


def test_null_notifier_logs_instead_of_delivering(caplog, monkeypatch):
    run = MagicMock()
    monkeypatch.setattr("maki.notifications.notifier.subprocess.run", run)

    with caplog.at_level(logging.INFO, logger="maki.notifications.notifier"):
        NullNotifier().notify(title="insights deployed", subtitle=None, body="fix thing", url=None)

    assert "notification suppressed" in caplog.text
    assert "insights deployed" in caplog.text and "fix thing" in caplog.text
    run.assert_not_called()


def test_build_notifier_is_null_off_darwin(monkeypatch):
    monkeypatch.setattr("maki.notifications.notifier.sys.platform", "linux")
    assert isinstance(build_notifier(), NullNotifier)


def test_build_notifier_is_null_under_the_test_suite():
    # conftest pins MAKI_NOTIFY_ENABLED=0, so no test raises a real banner even on darwin.
    assert isinstance(build_notifier(), NullNotifier)
