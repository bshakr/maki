"""Read-only CloudWatch Logs tail for one log group.

The operator has CLI-only AWS access (no console login), so the "open in CloudWatch" deep-link
bounces them to an unusable AWS sign-in page. ``LogTail`` instead fetches the recent log events
itself via ``logs:FilterLogEvents`` — interleaved across all streams in the group — and hands them
back so maki can render them in-app.

Error typing is explicit and asymmetric:

* **Credentials failure** (no creds / expired token) → let it PROPAGATE. The shared
  ``aws/errors.py`` handler turns it into the typed 503 ``aws_credentials_unavailable`` so the SPA
  can prompt a re-assume. We do NOT swallow it here.
* **``ResourceNotFoundException``** (the log group doesn't exist) → return a ``LogTailResult`` with
  ``error="not_found"``. This is a normal "service has no /ecs log group yet" state, not a 500.
* **``AccessDeniedException`` / authorization failure** → return ``error="forbidden"``. For a
  *logs* read this almost always means maki's role simply lacks ``logs:FilterLogEvents`` — a
  durable IAM gap, not a lapsed session — so we classify it here and surface a clear message with
  the console-link fallback instead of letting it propagate as a generic 500.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

# Authorization-failure error codes that mean "maki's role can't read these logs". Classified
# locally to a soft "forbidden" result so a durable IAM gap renders the console-link fallback
# rather than propagating as a generic 500.
_FORBIDDEN_CODES = frozenset({"AccessDeniedException", "AccessDenied"})

# Page-size cap per FilterLogEvents call (the API max is 10,000; we stay modest and page).
_PAGE_LIMIT = 1000

# Safety cap on pagination so a huge/busy window can never loop unboundedly.
_MAX_PAGES = 20


@dataclass(frozen=True)
class LogEvent:
    timestamp: datetime  # event time (UTC), from CloudWatch's epoch-millis ``timestamp``
    message: str
    stream: str  # the log stream the event came from


@dataclass(frozen=True)
class LogTailResult:
    """Outcome of a tail: either events, or a typed soft-failure the UI can explain.

    ``error`` is ``None`` on success, ``"not_found"`` when the log group is absent, or
    ``"forbidden"`` when maki's role lacks ``logs:FilterLogEvents``. ``truncated`` is True when the
    requested ``limit`` was hit before the window was exhausted (older events exist beyond the
    returned slice).
    """

    events: list[LogEvent]
    truncated: bool = False
    error: str | None = None


class LogTail:
    """Tail the most-recent events of a single CloudWatch log group, newest window first.

    Calls only ``logs:FilterLogEvents`` (interleaved across all streams). Reads the window
    ``[now - since_minutes, now]`` ascending and drains it (bounded by ``_MAX_PAGES``); the newest
    ``limit`` of the events gathered are returned in ascending (oldest-first) order, which reads
    naturally as a log tail.
    """

    def __init__(self, client, now=lambda: datetime.now(UTC)):
        self._client = client
        self._now = now

    def tail(self, log_group: str, limit: int = 200, since_minutes: int = 60) -> LogTailResult:
        end = self._now()
        start = end - timedelta(minutes=since_minutes)
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)

        events: list[LogEvent] = []
        next_token: str | None = None
        truncated = False
        try:
            for _ in range(_MAX_PAGES):
                kwargs = {
                    "logGroupName": log_group,
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "interleaved": True,
                    "limit": _PAGE_LIMIT,
                }
                if next_token:
                    kwargs["nextToken"] = next_token
                resp = self._client.filter_log_events(**kwargs)
                for raw in resp.get("events", []):
                    events.append(self._to_event(raw))
                next_token = resp.get("nextToken")
                if not next_token:
                    break
            else:
                # Hit the page cap with a token still pending -> there's more we didn't read.
                truncated = truncated or next_token is not None
        except Exception as exc:  # noqa: BLE001 - we classify; creds errors are re-raised below
            code = self._error_code(exc)
            if code == "ResourceNotFoundException":
                logger.info("log group %r not found", log_group)
                return LogTailResult(events=[], error="not_found")
            if code in _FORBIDDEN_CODES:
                logger.warning("forbidden reading logs for %r: %s", log_group, code)
                return LogTailResult(events=[], error="forbidden")
            # Anything else (incl. missing/expired creds) propagates: the shared AWS error handler
            # turns a creds failure into the typed 503, and a genuine fault into a 500.
            raise

        events.sort(key=lambda e: e.timestamp)
        if len(events) > limit:
            # Keep the newest ``limit`` (the tail) and flag that older events were dropped.
            events = events[-limit:]
            truncated = True
        return LogTailResult(events=events, truncated=truncated)

    @staticmethod
    def _to_event(raw: dict) -> LogEvent:
        ts_ms = raw.get("timestamp", 0)
        return LogEvent(
            timestamp=datetime.fromtimestamp(ts_ms / 1000, tz=UTC),
            message=(raw.get("message") or "").rstrip("\n"),
            stream=raw.get("logStreamName") or "",
        )

    @staticmethod
    def _error_code(exc: Exception) -> str | None:
        response = getattr(exc, "response", None)
        if isinstance(response, dict):
            return response.get("Error", {}).get("Code")
        return None
