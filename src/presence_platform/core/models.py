"""Core domain models.

The whole platform is built around ONE abstraction: an ``IdentitySource`` produces
a stream of normalized ``SessionEvent`` objects. Every backend (FreeRADIUS, Cisco ISE,
Aruba ClearPass, Cisco Spaces) is just an implementation of ``IdentitySource``.

Everything downstream (presence engine, storage, dashboard) works ONLY on
``SessionEvent`` and never knows which vendor produced it. That is what makes the
platform vendor-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator


class EventType(str, Enum):
    """Lifecycle of a network session."""

    START = "START"    # device authenticated / session began
    UPDATE = "UPDATE"  # interim update (still connected, maybe moved)
    STOP = "STOP"      # session ended / device left


@dataclass(frozen=True)
class SessionEvent:
    """The common event model.

    The single normalized record that EVERY identity source maps its raw data into.
    Immutable on purpose — these are facts that happened, an append-only audit trail.
    """

    user_id: str          # the authenticated identity (the person) — the STABLE key
    device_mac: str       # the device used (may be randomized; NOT a reliable identity)
    location_id: str      # where they connected (AP / controller / zone)
    event_type: EventType
    timestamp: int        # epoch milliseconds
    source: str           # which backend produced this (e.g. "freeradius", "cisco_ise")
    raw: dict[str, Any] = field(default_factory=dict)  # original untouched record

    def __post_init__(self) -> None:
        if not self.user_id:
            raise ValueError("SessionEvent requires a user_id (the identity).")
        if not isinstance(self.event_type, EventType):
            raise TypeError("event_type must be an EventType.")


class IdentitySource(ABC):
    """The central interface.

    A backend that can tell us who authenticated, where, and when.
    Implement this once per vendor. Nothing downstream changes when a new one is added.
    """

    #: short identifier for this source, e.g. "freeradius"
    name: str = "unknown"

    @abstractmethod
    def stream_sessions(self) -> Iterator[SessionEvent]:
        """Yield normalized SessionEvents as they occur.

        Implementations pull from their backend (tail an accounting log, consume a
        stream, poll an API) and translate each raw record into a SessionEvent.
        """
        raise NotImplementedError
