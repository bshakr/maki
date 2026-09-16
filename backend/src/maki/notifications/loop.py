"""The async driver loop for the deploy watcher.

Runs the (blocking) watch cycle on a worker thread so the event loop stays responsive, then
sleeps for the configured interval — waking early when the stop event is set on shutdown.
"""

import asyncio
import logging

from maki.notifications.watcher import DeployWatcher

logger = logging.getLogger(__name__)


async def watch_loop(watcher: DeployWatcher, interval_seconds: float, stop: asyncio.Event) -> None:
    """Run ``watcher.run_once()`` every ``interval_seconds`` until ``stop`` is set.

    A failing cycle is logged and the loop carries on; it never propagates out of the task.
    """
    while not stop.is_set():
        try:
            await asyncio.to_thread(watcher.run_once)
        except Exception:
            logger.exception("watch cycle failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass
