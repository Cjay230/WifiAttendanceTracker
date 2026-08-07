"""Presence engine.

WHY: raw SessionEvents (START / UPDATE / STOP) are not attendance. A manager does not
want an event log; they want "who is present, where, since when, and how sure are we."

WHAT: this turns a stream of SessionEvents into PresenceRecords using a small state
machine per (user, location). It handles the messy real cases:
  - a STOP that never arrives (dead phone) -> a timeout marks the user LEFT
  - short reconnects -> a grace window keeps it as one visit, not two
  - confidence -> we track how recently we last heard from the user, so the product can
    say "present (confirmed 1 min ago)" vs "present (last seen 40 min ago)" instead of
    pretending certainty.

The engine never invents identity. user_id always comes from the source (the login).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from presence_platform.core.models import EventType, SessionEvent


class PresenceState(str, Enum):
    """Where a user is in the presence lifecycle."""

    ABSENT = "ABSENT"    # not seen / has left
    PRESENT = "PRESENT"  # confirmed here recently
    IDLE = "IDLE"        # still counted present, but not heard from in a while
    LEFT = "LEFT"        # session ended (clean STOP or timeout)


@dataclass
class PresenceRecord:
    """One attendance record for a user at a location.

    A visit: when they arrived, when we last saw them, when they left (if they did),
    and our current confidence in it.
    """

    user_id: str
    location_id: str
    check_in: int                 # epoch ms of first START
    last_seen: int                # epoch ms of the most recent event
    state: PresenceState
    check_out: int | None = None  # epoch ms when LEFT (None if still present)
    source: str = ""
    # WHY: check_out/last_seen alone can't tell a clean STOP from a timed-out visit (both
    # land on the same value). Callers doing stats (e.g. scale-test reporting) need this.
    ended_reason: str | None = None  # "stop" | "timeout" | None (still open)

    @property
    def duration_ms(self) -> int:
        """How long the visit lasted so far (or in total if ended)."""
        end = self.check_out if self.check_out is not None else self.last_seen
        return end - self.check_in


@dataclass
class PresenceEngine:
    """Turns SessionEvents into PresenceRecords via a per-user-per-location state machine.

    WHY the two timeouts:
      - idle_timeout: no word from a user for this long -> mark IDLE (present but unsure).
      - left_timeout: no word for this long -> assume they LEFT (handles missing STOP).
      - reconnect_grace: a new START within this window of a STOP = same visit, not a new one.

    All are in milliseconds and configurable, because a call centre and an office have
    different rhythms. Defaults are deliberately conservative.
    """

    idle_timeout_ms: int = 5 * 60 * 1000    # 5 min quiet -> IDLE
    left_timeout_ms: int = 15 * 60 * 1000   # 15 min quiet -> LEFT (missing-STOP safety net)
    reconnect_grace_ms: int = 2 * 60 * 1000  # rejoin within 2 min of STOP = same visit

    # active visits keyed by (user_id, location_id)
    _active: dict[tuple[str, str], PresenceRecord] = field(default_factory=dict)
    # finished visits (ended by STOP or timeout)
    _completed: list[PresenceRecord] = field(default_factory=list)
    # most recent STOPped record per key, kept only as a reconnect-grace candidate
    _recently_stopped: dict[tuple[str, str], PresenceRecord] = field(default_factory=dict)

    def process(self, event: SessionEvent) -> None:
        """Feed one event into the state machine.

        WHY expire AFTER handling this event, not before: an event about a user is proof
        we just heard from *them*. If we expired first using this event's timestamp, a
        legitimately late STOP (e.g. a 60-min session with no interim updates) would time
        out its own visit before it could close it. So: handle the event first (it closes
        or refreshes its own visit), then expire *other* users who have gone quiet.
        """
        key = (event.user_id, event.location_id)

        if event.event_type in (EventType.START, EventType.UPDATE):
            self._on_seen(key, event)
        elif event.event_type == EventType.STOP:
            self._on_stop(key, event)

        # Now expire anyone ELSE who has gone quiet too long, as of this event's time.
        self._expire_stale(now=event.timestamp, skip=key)

    def _on_seen(self, key: tuple[str, str], event: SessionEvent) -> None:
        """START or UPDATE: user is here. Open a visit, reopen a recent one, or refresh."""
        record = self._active.get(key)
        if record is None:
            record = self._reopen_if_within_grace(key, event.timestamp)
        if record is None:
            # genuinely new visit
            record = PresenceRecord(
                user_id=event.user_id,
                location_id=event.location_id,
                check_in=event.timestamp,
                last_seen=event.timestamp,
                state=PresenceState.PRESENT,
                source=event.source,
            )
            self._active[key] = record
        else:
            # existing (or reopened) visit: refresh, confirm present
            record.last_seen = event.timestamp
            record.state = PresenceState.PRESENT

    def _reopen_if_within_grace(self, key: tuple[str, str], now: int) -> PresenceRecord | None:
        """WHY: a STOP closes a visit immediately, but real devices reconnect quickly
        (sleep/wake, a brief signal drop) without that meaning a new visit. If a START
        arrives within reconnect_grace_ms of that STOP, treat it as the same visit
        instead of opening a new one.
        """
        stopped = self._recently_stopped.pop(key, None)
        if stopped is None:
            return None
        if now - stopped.check_out > self.reconnect_grace_ms:
            return None  # too late; it stays closed, a genuinely new visit follows

        # reopen: undo the STOP, drop it from completed, put it back in _active
        for i, r in enumerate(self._completed):
            if r is stopped:
                del self._completed[i]
                break
        stopped.check_out = None
        stopped.ended_reason = None
        stopped.state = PresenceState.PRESENT
        self._active[key] = stopped
        return stopped

    def _on_stop(self, key: tuple[str, str], event: SessionEvent) -> None:
        """STOP: user left cleanly. Close the visit."""
        record = self._active.pop(key, None)
        if record is None:
            return  # STOP with no matching open visit -> ignore
        record.last_seen = event.timestamp
        record.check_out = event.timestamp
        record.state = PresenceState.LEFT
        record.ended_reason = "stop"
        self._completed.append(record)
        self._recently_stopped[key] = record  # candidate for reconnect-grace merge

    def _expire_stale(self, now: int, skip: tuple[str, str] | None = None) -> None:
        """Apply timeouts: quiet visits go IDLE, then LEFT.

        `skip` is the visit we just handled this tick — never expire it based on the
        very event that refreshed it.
        """
        for key in list(self._active.keys()):
            if key == skip:
                continue
            record = self._active[key]
            quiet_for = now - record.last_seen
            if quiet_for >= self.left_timeout_ms:
                # assume left (missing STOP) — check_out is the last time we actually saw them
                record.check_out = record.last_seen
                record.state = PresenceState.LEFT
                record.ended_reason = "timeout"
                self._completed.append(record)
                del self._active[key]
            elif quiet_for >= self.idle_timeout_ms:
                record.state = PresenceState.IDLE

    def finalize(self, now: int | None = None) -> None:
        """Call when the stream ends. Expire anything stale as of `now`.

        WHY: at end of input, some visits are still open. If `now` is given we apply
        timeouts one last time; visits still within timeout stay PRESENT/IDLE (open).
        """
        if now is not None:
            self._expire_stale(now=now)

    def current_presence(self) -> list[PresenceRecord]:
        """Everyone currently considered here (PRESENT or IDLE)."""
        return list(self._active.values())

    def completed_visits(self) -> list[PresenceRecord]:
        """All finished visits (LEFT by STOP or timeout)."""
        return list(self._completed)

    def all_records(self) -> list[PresenceRecord]:
        """Everything: active + completed."""
        return self.current_presence() + self.completed_visits()


def build_presence(events: Iterable[SessionEvent], **engine_kwargs) -> PresenceEngine:
    """Convenience: run a whole stream of events through a fresh engine.

    Events should arrive in time order. Returns the engine so you can query
    current_presence() / completed_visits().
    """
    engine = PresenceEngine(**engine_kwargs)
    last_ts = 0
    for event in events:
        engine.process(event)
        last_ts = max(last_ts, event.timestamp)
    engine.finalize(now=last_ts)
    return engine
