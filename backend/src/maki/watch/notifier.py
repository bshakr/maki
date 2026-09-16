"""macOS delivery for deploy notifications.

This is the only subprocess in maki. It is local desktop UI — it does not touch AWS, GitHub, or
any deploy. Command arguments are always passed as a list; no user-supplied text (a commit
message, a job name) is ever interpolated into a shell string.
"""

import logging
import shutil
import subprocess
import sys
from collections.abc import Callable
from typing import Protocol

from maki.settings import settings

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    def notify(self, *, title: str, subtitle: str | None, body: str, url: str | None) -> None: ...


class NullNotifier:
    """Used when notifications are disabled or the host isn't macOS."""

    def notify(self, *, title: str, subtitle: str | None, body: str, url: str | None) -> None:
        logger.info("notification suppressed: %s — %s", title, body)


def _escape(value: str) -> str:
    """Escape for an AppleScript double-quoted literal. Backslash first, then quote."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _applescript(title: str, subtitle: str | None, body: str) -> str:
    script = f'display notification "{_escape(body)}" with title "{_escape(title)}"'
    if subtitle:
        script += f' subtitle "{_escape(subtitle)}"'
    return script


class MacNotifier:
    """Deliver via terminal-notifier when installed, else osascript.

    terminal-notifier is preferred because it takes argv (no AppleScript escaping to get wrong)
    and its -open flag makes the notification click through to the maki page for the deploy.
    """

    def __init__(
        self,
        runner: Callable[..., object] = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
    ):
        self._run = runner
        self._which = which

    def notify(self, *, title: str, subtitle: str | None, body: str, url: str | None) -> None:
        binary = self._which("terminal-notifier")
        if binary:
            argv = [binary, "-title", title, "-message", body]
            if subtitle:
                argv += ["-subtitle", subtitle]
            if url:
                argv += ["-open", url]
        else:
            argv = ["osascript", "-e", _applescript(title, subtitle, body)]
        try:
            self._run(argv, timeout=5, check=False, capture_output=True)
        except Exception:
            # A failed notification must never take down the watcher cycle.
            logger.warning("notification delivery failed", exc_info=True)


def build_notifier() -> Notifier:
    if not settings.notify_enabled or sys.platform != "darwin":
        return NullNotifier()
    return MacNotifier()
