"""FreeRADIUS identity source.

Reads a FreeRADIUS detail accounting file and turns each record into a
normalized SessionEvent. First concrete implementation of IdentitySource.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from presence_platform.core.models import EventType, IdentitySource, SessionEvent

_STATUS_MAP = {
    "Start": EventType.START,
    "Interim-Update": EventType.UPDATE,
    "Stop": EventType.STOP,
}


def _parse_records(lines: Iterator[str]) -> Iterator[dict[str, str]]:
    record: dict[str, str] = {}
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip():
            if record:
                yield record
                record = {}
            continue
        if not line.startswith((" ", "\t")):
            record["_header"] = line.strip()
            continue
        if "=" in line:
            key, _, value = line.strip().partition("=")
            record[key.strip()] = value.strip().strip('"')
    if record:
        yield record


def _to_event(record: dict[str, str], source_name: str) -> SessionEvent | None:
    status = record.get("Acct-Status-Type")
    event_type = _STATUS_MAP.get(status)
    if event_type is None:
        return None

    user = record.get("User-Name")
    if not user:
        return None

    ts_raw = record.get("Timestamp")
    timestamp = int(ts_raw) * 1000 if ts_raw and ts_raw.isdigit() else 0

    return SessionEvent(
        user_id=user,
        device_mac=record.get("Calling-Station-Id", ""),
        location_id=record.get("Called-Station-Id", ""),
        event_type=event_type,
        timestamp=timestamp,
        source=source_name,
        raw=dict(record),
    )


class FreeRADIUSSource(IdentitySource):
    """Reads a FreeRADIUS detail accounting file and yields SessionEvents."""

    name = "freeradius"

    def __init__(self, detail_path: str | Path):
        self.detail_path = Path(detail_path)

    def stream_sessions(self) -> Iterator[SessionEvent]:
        with self.detail_path.open("r", encoding="utf-8", errors="ignore") as f:
            for record in _parse_records(f):
                event = _to_event(record, self.name)
                if event is not None:
                    yield event
