import logging
from unittest.mock import MagicMock

from maki.watch.notifier import MacNotifier, NullNotifier, build_notifier


def test_prefers_terminal_notifier_when_present():
    runner = MagicMock()
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
    runner = MagicMock()
    notifier = MacNotifier(runner=runner, which=lambda _: None)

    notifier.notify(title="t", subtitle="s", body="b", url=None)

    argv = runner.call_args.args[0]
    assert argv[0] == "osascript"
    assert argv[1] == "-e"
    assert argv[2] == 'display notification "b" with title "t" subtitle "s"'


def test_osascript_escapes_quotes_and_backslashes():
    runner = MagicMock()
    notifier = MacNotifier(runner=runner, which=lambda _: None)

    notifier.notify(title="t", subtitle=None, body='say "hi" \\ bye', url=None)

    script = runner.call_args.args[0][2]
    assert script == 'display notification "say \\"hi\\" \\\\ bye" with title "t"'


def test_never_uses_a_shell():
    runner = MagicMock()
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
    monkeypatch.setattr("maki.watch.notifier.subprocess.run", run)

    with caplog.at_level(logging.INFO, logger="maki.watch.notifier"):
        NullNotifier().notify(title="insights deployed", subtitle=None, body="fix thing", url=None)

    assert "notification suppressed" in caplog.text
    assert "insights deployed" in caplog.text and "fix thing" in caplog.text
    run.assert_not_called()


def test_build_notifier_is_null_off_darwin(monkeypatch):
    monkeypatch.setattr("maki.watch.notifier.sys.platform", "linux")
    assert isinstance(build_notifier(), NullNotifier)
