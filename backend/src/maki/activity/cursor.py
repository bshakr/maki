"""Opaque keyset cursor codec, shared by the activity feed and per-service history paging.

A cursor encodes the ``(sort_ts, id)`` of the last row on a page so the next page can resume
strictly after it in that endpoint's ``<sort_ts> DESC, id DESC`` ordering. The activity feed sorts
by ``COALESCE(finished_at, registered_at)``; per-service history (``history/``) sorts by
``registered_at``. The codec is agnostic to which timestamp it carries — both import it.

The wire format is URL-safe base64 of ``<iso8601>_<id>`` — opaque to the client (it should round-
trip the string verbatim), but trivially debuggable by base64-decoding it.
"""

import base64
import binascii
from datetime import datetime


class InvalidCursor(ValueError):
    """Raised when a cursor string can't be decoded into a ``(deployed_at, id)`` pair."""


def encode_cursor(deployed_at: datetime, event_id: int) -> str:
    """Encode a ``(deployed_at, id)`` keyset position into an opaque cursor string."""
    raw = f"{deployed_at.isoformat()}_{event_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    """Decode an opaque cursor back into ``(deployed_at, id)``.

    Raises ``InvalidCursor`` on any malformed input so the route can return a clean 422 rather
    than a 500.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        iso, _, id_str = raw.rpartition("_")
        if not iso:
            raise InvalidCursor(cursor)
        return datetime.fromisoformat(iso), int(id_str)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCursor(cursor) from exc
