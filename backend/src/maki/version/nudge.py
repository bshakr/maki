"""Terminal nudge: one line when the clone is behind its upstream, silence otherwise.

Run by ``make dev`` / ``make backend`` before starting servers. Must never fail or block
the build — check failures are silent and the process always exits 0.
"""

from maki.version.service import check_version

# Match the Makefile's ✓/!/cyan markers so the line reads like the rest of the tooling.
WARN = "\033[33m!\033[0m"
CYAN = "\033[36m"
RESET = "\033[0m"


def main() -> None:
    status = check_version()
    if not status.update_available:
        return
    where = status.upstream
    if status.behind_by:
        plural = "" if status.behind_by == 1 else "s"
        behind = f"{status.behind_by} commit{plural} behind {where}"
    else:
        behind = f"behind {where}"
    print(f"{WARN} maki: {behind} — run {CYAN}make update{RESET} to get the latest")


if __name__ == "__main__":
    main()
