"""Confirmation layer (login + body fusion).

WHY: the presence engine answers ONE question from the network login alone:
"is there an active, recent session for this user here?" (PRESENT / IDLE / LEFT).
That is certain identity, but it only proves a *logged-in device* is here â€” not that
the *person* is. A shared badge, a proxy login, or a laptop left on all night all read
as PRESENT.

WHAT: this layer adds a SECOND, independent axis â€” "is a real body confirmed?" â€” by
fusing the engine's login-based PresenceRecord with a gait observation (from the BFI
layer; simulated for now). Login is the GATE: no active login record => nothing to
confirm, and gait ALONE never creates presence. Gait only ANNOTATES an existing
login-based visit with a confidence.

These two axes are orthogonal on purpose. A user can be PRESENT (login fresh) yet
UNCONFIRMED (no body match) at the same time. We keep them in separate fields so
neither question muddies the other, and so the engine stays completely untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from presence_platform.pipeline.presence_engine import PresenceRecord, PresenceState


class ConfirmationState(str, Enum):
    """The body-confirmation axis. Independent of PresenceState (the login axis)."""

    CONFIRMED = "CONFIRMED"            # login active + strong gait match
    LOW_CONFIDENCE = "LOW_CONFIDENCE"  # login active + weak-ish gait match
    UNCONFIRMED = "UNCONFIRMED"        # login active + gait says "not this body" -> FLAG
    PENDING = "PENDING"               # login active, no gait observed yet (still waiting)
    NO_PRESENCE = "NO_PRESENCE"        # no active login record -> nothing to confirm


# Confidence bands on the gait match score (0.0â€“1.0).
# WHY these three: CONFIRMED = trust it; LOW_CONFIDENCE = present but say so honestly;
# UNCONFIRMED = the gait actively disagrees, worth a human look (proxy / badge-share).
CONFIRM_THRESHOLD = 0.85   # >= this -> CONFIRMED
LOW_THRESHOLD = 0.50       # [LOW, CONFIRM) -> LOW_CONFIDENCE ; below -> UNCONFIRMED


@dataclass(frozen=True)
class GaitObservation:
    """One body-identification result from the BFI layer.

    ``match_score`` is the model's confidence (0.0â€“1.0) that the body walking past
    matches ``user_id``'s enrolled gait profile. For the PoC this is fed in by hand /
    synthetic; later it comes from the trained LSTM.
    """

    user_id: str
    location_id: str
    match_score: float   # 0.0â€“1.0
    timestamp: int       # epoch ms the walk was observed

    def __post_init__(self) -> None:
        if not 0.0 <= self.match_score <= 1.0:
            raise ValueError("match_score must be between 0.0 and 1.0")


@dataclass(frozen=True)
class ConfirmedPresence:
    """A login-based visit annotated with a body-confirmation verdict.

    Wraps the engine's PresenceRecord (never replaces it) and adds the second axis.
    """

    record: PresenceRecord
    confirmation_state: ConfirmationState
    confidence: float | None  # the gait score used, or None when no gait / no presence

    # convenience passthroughs so callers don't have to reach into .record
    @property
    def user_id(self) -> str:
        return self.record.user_id

    @property
    def location_id(self) -> str:
        return self.record.location_id

    @property
    def login_state(self) -> PresenceState:
        """The login axis (from the engine), kept distinct from the body axis."""
        return self.record.state


def confirm(
    record: PresenceRecord | None,
    gait: GaitObservation | None,
    *,
    now: int,
    pending_timeout_ms: int,
) -> ConfirmedPresence | None:
    """Fuse one login-based PresenceRecord with one gait observation.

    WHY the login gate first: this enforces the locked principle. If there is no active
    login record, there is nothing to confirm and gait alone must never manufacture a
    presence â€” we return NO_PRESENCE (or None if there's genuinely no record at all).

    ``now`` and ``pending_timeout_ms`` only matter for the no-gait case: a freshly
    logged-in user hasn't necessarily walked past a sensor yet, so we hold PENDING for a
    while before settling to LOW_CONFIDENCE (assume "sitting out of sensor range", don't
    punish them by flagging).
    """
    # --- login gate -------------------------------------------------------------
    if record is None:
        return None  # no visit at all -> caller has nothing to show
    if record.state in (PresenceState.LEFT, PresenceState.ABSENT):
        # login says the visit is over -> body confirmation is moot
        return ConfirmedPresence(record, ConfirmationState.NO_PRESENCE, None)

    # --- no gait yet ------------------------------------------------------------
    if gait is None:
        # How long has this login-visit been open without any body signal?
        waited = now - record.check_in
        if waited < pending_timeout_ms:
            return ConfirmedPresence(record, ConfirmationState.PENDING, None)
        # waited long enough with no walk-by: present per login, body just unseen
        return ConfirmedPresence(record, ConfirmationState.LOW_CONFIDENCE, None)

    # --- gait present: band the score ------------------------------------------
    # (PoC: any gait match in the visit counts; no freshness check yet â€” that's a
    #  later refinement, per decision.)
    score = gait.match_score
    if score >= CONFIRM_THRESHOLD:
        state = ConfirmationState.CONFIRMED
    elif score >= LOW_THRESHOLD:
        state = ConfirmationState.LOW_CONFIDENCE
    else:
        state = ConfirmationState.UNCONFIRMED  # gait disagrees -> flag for review
    return ConfirmedPresence(record, state, score)
