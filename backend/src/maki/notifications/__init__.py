"""Deploy notifications for watched services: the watcher, its loop, and macOS delivery."""

from maki.notifications.loop import watch_loop
from maki.notifications.watcher import DeployWatcher, build_watcher

__all__ = ["DeployWatcher", "build_watcher", "watch_loop"]
