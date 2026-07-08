from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError, NoCredentialsError

from maki.aws.logs import _MAX_PAGES, LogTail

# Fixed "now" so the window [now-since, now] is deterministic.
NOW = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _event(ts: datetime, message: str, stream: str) -> dict:
    return {"timestamp": _ms(ts), "message": message, "logStreamName": stream}


def _client(pages):
    """A logs client whose filter_log_events returns the given list of response dicts in order."""
    client = MagicMock()
    client.filter_log_events.side_effect = list(pages)
    return client


def _tail(client) -> LogTail:
    return LogTail(client, now=lambda: NOW)


def test_returns_events_ascending_with_fields():
    t0 = datetime(2026, 6, 5, 11, 58, tzinfo=UTC)
    t1 = datetime(2026, 6, 5, 11, 59, tzinfo=UTC)
    client = _client(
        [
            {
                "events": [
                    _event(t1, "second\n", "stream-b"),
                    _event(t0, "first", "stream-a"),
                ]
            }
        ]
    )
    result = _tail(client).tail("/ecs/inventory-production")

    assert result.error is None
    assert result.truncated is False
    assert [e.timestamp for e in result.events] == [t0, t1]  # ascending
    assert [e.message for e in result.events] == ["first", "second"]  # trailing \n stripped
    assert [e.stream for e in result.events] == ["stream-a", "stream-b"]


def test_passes_interleaved_window_and_group():
    client = _client([{"events": []}])
    _tail(client).tail("/ecs/inventory-production", limit=50, since_minutes=30)

    kwargs = client.filter_log_events.call_args.kwargs
    assert kwargs["logGroupName"] == "/ecs/inventory-production"
    assert kwargs["interleaved"] is True
    assert kwargs["endTime"] == _ms(NOW)
    # since_minutes=30 → start is 30 minutes before NOW.
    assert kwargs["startTime"] == _ms(datetime(2026, 6, 5, 11, 30, tzinfo=UTC))


def test_keeps_newest_when_window_exceeds_limit():
    # Two pages, each one event; a nextToken keeps paging. limit=1 drains both pages, then keeps
    # only the newest event, so truncated is True.
    t0 = datetime(2026, 6, 5, 11, 50, tzinfo=UTC)
    t1 = datetime(2026, 6, 5, 11, 55, tzinfo=UTC)
    client = _client(
        [
            {"events": [_event(t0, "a", "s")], "nextToken": "tok"},
            {"events": [_event(t1, "b", "s")]},
        ]
    )
    result = _tail(client).tail("/ecs/inventory-production", limit=1)

    assert result.truncated is True
    # Both pages were read (window drained), not just the first.
    assert client.filter_log_events.call_count == 2
    assert [e.message for e in result.events] == ["b"]


def test_page_cap_marks_truncated():
    # Every page reports a nextToken, so the loop only stops when _MAX_PAGES is hit.
    pages = [
        {
            "events": [_event(datetime(2026, 6, 5, 11, 50, tzinfo=UTC), str(i), "s")],
            "nextToken": "tok",
        }
        for i in range(_MAX_PAGES)
    ]
    client = _client(pages)
    result = _tail(client).tail("/ecs/inventory-production", limit=200)

    assert result.truncated is True
    assert client.filter_log_events.call_count == _MAX_PAGES


def test_drains_window_when_under_limit():
    t0 = datetime(2026, 6, 5, 11, 50, tzinfo=UTC)
    t1 = datetime(2026, 6, 5, 11, 55, tzinfo=UTC)
    client = _client(
        [
            {"events": [_event(t0, "a", "s")], "nextToken": "tok"},
            {"events": [_event(t1, "b", "s")]},  # no nextToken → window exhausted
        ]
    )
    result = _tail(client).tail("/ecs/inventory-production", limit=200)

    assert result.truncated is False
    assert client.filter_log_events.call_count == 2
    assert [e.message for e in result.events] == ["a", "b"]


def test_resource_not_found_returns_not_found():
    client = MagicMock()
    client.filter_log_events.side_effect = ClientError(
        {"Error": {"Code": "ResourceNotFoundException", "Message": "no group"}},
        "FilterLogEvents",
    )
    result = _tail(client).tail("/ecs/missing-production")

    assert result.error == "not_found"
    assert result.events == []


def test_access_denied_returns_forbidden_not_503():
    client = MagicMock()
    client.filter_log_events.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "denied"}},
        "FilterLogEvents",
    )
    result = _tail(client).tail("/ecs/inventory-production")

    # Must NOT propagate (which would be mis-classified as an expired-creds 503); it's a durable
    # IAM gap on logs:FilterLogEvents.
    assert result.error == "forbidden"
    assert result.events == []


def test_credentials_error_propagates():
    client = MagicMock()
    client.filter_log_events.side_effect = NoCredentialsError()

    # Propagates so the shared AWS error handler turns it into the typed 503.
    with pytest.raises(NoCredentialsError):
        _tail(client).tail("/ecs/inventory-production")


def test_unexpected_client_error_propagates():
    client = MagicMock()
    client.filter_log_events.side_effect = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow down"}},
        "FilterLogEvents",
    )
    with pytest.raises(ClientError):
        _tail(client).tail("/ecs/inventory-production")
