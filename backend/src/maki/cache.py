import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any


class SwrCache:
    """Stale-while-revalidate cache. Serve cached instantly; refresh in the background once past
    `fresh_seconds`; block-and-recompute when cold, past `stale_seconds`, or forced."""

    def __init__(
        self, fresh_seconds: float, stale_seconds: float, executor: ThreadPoolExecutor | None = None
    ):
        self._fresh = fresh_seconds
        self._stale = stale_seconds
        self._executor = executor or ThreadPoolExecutor(max_workers=4, thread_name_prefix="swr")
        self._lock = threading.Lock()
        self._entries: dict[Any, tuple[float, Any]] = {}  # key -> (monotonic_ts, value)
        self._inflight: set[Any] = set()

    def get(self, key: Any, loader: Callable[[], Any], force: bool = False) -> Any:
        with self._lock:
            entry = self._entries.get(key)
        if force or entry is None:
            return self._load_blocking(key, loader)
        age = time.monotonic() - entry[0]
        if age <= self._fresh:
            return entry[1]  # fresh: serve as-is
        if age <= self._stale:
            self._refresh_async(key, loader)  # stale-but-ok: serve + background refresh
            return entry[1]
        return self._load_blocking(key, loader)  # too stale: block + recompute

    def _load_blocking(self, key: Any, loader: Callable[[], Any]) -> Any:
        value = loader()
        with self._lock:
            self._entries[key] = (time.monotonic(), value)
        return value

    def _refresh_async(self, key: Any, loader: Callable[[], Any]) -> None:
        with self._lock:
            if key in self._inflight:
                return
            self._inflight.add(key)

        def task() -> None:
            try:
                value = loader()
                with self._lock:
                    self._entries[key] = (time.monotonic(), value)
            except Exception:
                pass  # keep serving last good value on refresh failure
            finally:
                with self._lock:
                    self._inflight.discard(key)

        self._executor.submit(task)
