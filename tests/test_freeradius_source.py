"""Tests for FreeRADIUSSource against a detail-file fixture."""

from pathlib import Path

from presence_platform.core.models import EventType
from presence_platform.sources.freeradius.source import FreeRADIUSSource

FIXTURE = Path(__file__).parent / "fixtures" / "detail-sample"


def test_parses_start_and_stop():
    events = list(FreeRADIUSSource(FIXTURE).stream_sessions())
    assert len(events) == 2
    start, stop = events
    assert start.event_type == EventType.START
    assert start.user_id == "rita"
    assert start.location_id == "AP-Floor3"
    assert stop.event_type == EventType.STOP


def test_timestamp_converted_to_millis():
    start = next(FreeRADIUSSource(FIXTURE).stream_sessions())
    assert start.timestamp == 1786004819000
