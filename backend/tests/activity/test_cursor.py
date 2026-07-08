from datetime import UTC, datetime

import pytest

from maki.activity.cursor import InvalidCursor, decode_cursor, encode_cursor


def test_round_trips_deployed_at_and_id():
    deployed_at = datetime(2026, 5, 31, 8, 0, tzinfo=UTC)
    cursor = encode_cursor(deployed_at, 4242)
    assert decode_cursor(cursor) == (deployed_at, 4242)


def test_cursor_is_opaque_not_the_raw_pair():
    cursor = encode_cursor(datetime(2026, 5, 31, 8, 0, tzinfo=UTC), 7)
    assert "_" not in cursor  # base64-wrapped, not the bare "<iso>_<id>"
    assert "2026" not in cursor


def test_decode_rejects_garbage():
    with pytest.raises(InvalidCursor):
        decode_cursor("not-a-real-cursor!!!")


def test_decode_rejects_non_base64():
    with pytest.raises(InvalidCursor):
        decode_cursor("@@@@")


def test_decode_rejects_missing_id():
    # base64 of "2026-05-31T08:00:00+00:00" with no "_<id>" suffix.
    import base64

    bad = base64.urlsafe_b64encode(b"2026-05-31T08:00:00+00:00").decode()
    with pytest.raises(InvalidCursor):
        decode_cursor(bad)
