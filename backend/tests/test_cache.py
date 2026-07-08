from concurrent.futures import ThreadPoolExecutor

from maki.cache import SwrCache


def test_serves_cached_within_fresh_window():
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return calls["n"]

    c = SwrCache(fresh_seconds=100, stale_seconds=100)
    assert c.get("k", loader) == 1  # cold → blocks → 1
    assert c.get("k", loader) == 1  # fresh → cached, loader not called again
    assert calls["n"] == 1


def test_force_bypasses_cache():
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return calls["n"]

    c = SwrCache(fresh_seconds=100, stale_seconds=100)
    c.get("k", loader)
    assert c.get("k", loader, force=True) == 2


def test_stale_serves_old_then_refreshes_in_background():
    ex = ThreadPoolExecutor(max_workers=1)
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return calls["n"]

    c = SwrCache(fresh_seconds=-1, stale_seconds=100, executor=ex)  # fresh=-1 → always "stale"
    assert c.get("k", loader) == 1  # cold blocks → 1
    assert c.get("k", loader) == 1  # stale: serves old (1) + bg refresh to 2
    ex.shutdown(wait=True)  # let bg refresh finish
    assert calls["n"] == 2
    # entry is now refreshed to 2; read the stored value directly (executor is shut down,
    # and another stale read would try to schedule a refresh on the dead executor).
    assert c._entries["k"][1] == 2  # now holds refreshed value


def test_blocks_when_past_stale_bound():
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return calls["n"]

    c = SwrCache(fresh_seconds=-2, stale_seconds=-1)  # everything too stale → always blocks
    c.get("k", loader)
    c.get("k", loader)
    assert calls["n"] == 2


def test_separate_keys_have_separate_entries():
    calls = {"a": 0, "b": 0}

    def loader_a():
        calls["a"] += 1
        return f"a{calls['a']}"

    def loader_b():
        calls["b"] += 1
        return f"b{calls['b']}"

    c = SwrCache(fresh_seconds=100, stale_seconds=100)
    assert c.get("a", loader_a) == "a1"
    assert c.get("b", loader_b) == "b1"
    assert c.get("a", loader_a) == "a1"  # still cached independently
    assert calls == {"a": 1, "b": 1}


def test_background_refresh_failure_keeps_last_good_value():
    ex = ThreadPoolExecutor(max_workers=1)
    state = {"n": 0}

    def loader():
        state["n"] += 1
        if state["n"] == 1:
            return "good"
        raise RuntimeError("boom")

    c = SwrCache(fresh_seconds=-1, stale_seconds=100, executor=ex)
    assert c.get("k", loader) == "good"  # cold → blocks → good
    assert c.get("k", loader) == "good"  # stale: serves good + bg refresh (which raises)
    ex.shutdown(wait=True)  # bg refresh ran and failed
    assert state["n"] == 2  # refresh attempted
    assert c._entries["k"][1] == "good"  # still holds last good value, not poisoned


def test_single_flight_refresh_does_not_double_submit():
    # Block the executor with a slow refresh, then trigger several stale reads;
    # only one refresh task should be in flight.
    import threading

    started = threading.Event()
    release = threading.Event()
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        if calls["n"] > 1:
            started.set()
            release.wait(2.0)
        return calls["n"]

    ex = ThreadPoolExecutor(max_workers=2)
    c = SwrCache(fresh_seconds=-1, stale_seconds=100, executor=ex)
    assert c.get("k", loader) == 1  # cold blocks → 1
    c.get("k", loader)  # stale → schedules refresh #1 (will block in loader)
    started.wait(2.0)
    c.get("k", loader)  # stale → refresh already inflight, must NOT schedule another
    c.get("k", loader)
    release.set()
    ex.shutdown(wait=True)
    assert calls["n"] == 2  # exactly one background refresh ran
