"""Tests for the confirmation (login + body fusion) layer.

Covers the full matrix: login gate (present / left / none) x gait band
(strong / mid / weak / none-within-timeout / none-past-timeout).
"""

from __future__ import annotations

import pytest

from presence_platform.pipeline.presence_engine import PresenceRecord, PresenceState
from presence_platform.pipeline.confirmation import (
    ConfirmationState,
    GaitObservation,
    confirm,
)

PENDING_TIMEOUT = 5 * 60 * 1000  # 5 min, matches engine idle_timeout


def _rec(state=PresenceState.PRESENT, check_in=0, last_seen=1000):
    return PresenceRecord(
        user_id="alice", location_id="ap-3",
        check_in=check_in, last_seen=last_seen, state=state, source="freeradius",
    )


def _gait(score):
    return GaitObservation("alice", "ap-3", match_score=score, timestamp=1000)


# --- login gate: no presence -> gait can't manufacture one ----------------------

def test_no_record_returns_none():
    assert confirm(None, _gait(0.99), now=1000, pending_timeout_ms=PENDING_TIMEOUT) is None

def test_left_record_is_no_presence_even_with_perfect_gait():
    cp = confirm(_rec(PresenceState.LEFT), _gait(0.99), now=1000, pending_timeout_ms=PENDING_TIMEOUT)
    assert cp.confirmation_state is ConfirmationState.NO_PRESENCE
    assert cp.confidence is None

def test_absent_record_is_no_presence():
    cp = confirm(_rec(PresenceState.ABSENT), _gait(0.99), now=1000, pending_timeout_ms=PENDING_TIMEOUT)
    assert cp.confirmation_state is ConfirmationState.NO_PRESENCE


# --- login present + gait bands -------------------------------------------------

def test_strong_gait_confirms():
    cp = confirm(_rec(), _gait(0.90), now=1000, pending_timeout_ms=PENDING_TIMEOUT)
    assert cp.confirmation_state is ConfirmationState.CONFIRMED
    assert cp.confidence == 0.90

def test_mid_gait_low_confidence():
    cp = confirm(_rec(), _gait(0.65), now=1000, pending_timeout_ms=PENDING_TIMEOUT)
    assert cp.confirmation_state is ConfirmationState.LOW_CONFIDENCE

def test_weak_gait_unconfirmed_flag():
    cp = confirm(_rec(), _gait(0.20), now=1000, pending_timeout_ms=PENDING_TIMEOUT)
    assert cp.confirmation_state is ConfirmationState.UNCONFIRMED

def test_band_edges_are_inclusive_lower():
    # exactly 0.85 -> CONFIRMED ; exactly 0.50 -> LOW_CONFIDENCE
    assert confirm(_rec(), _gait(0.85), now=1000, pending_timeout_ms=PENDING_TIMEOUT).confirmation_state is ConfirmationState.CONFIRMED
    assert confirm(_rec(), _gait(0.50), now=1000, pending_timeout_ms=PENDING_TIMEOUT).confirmation_state is ConfirmationState.LOW_CONFIDENCE
    # just under 0.50 -> UNCONFIRMED
    assert confirm(_rec(), _gait(0.4999), now=1000, pending_timeout_ms=PENDING_TIMEOUT).confirmation_state is ConfirmationState.UNCONFIRMED


# --- login present + NO gait: PENDING then LOW_CONFIDENCE -----------------------

def test_no_gait_within_timeout_is_pending():
    cp = confirm(_rec(check_in=0), None, now=60_000, pending_timeout_ms=PENDING_TIMEOUT)  # 1 min in
    assert cp.confirmation_state is ConfirmationState.PENDING
    assert cp.confidence is None

def test_no_gait_past_timeout_is_low_confidence():
    cp = confirm(_rec(check_in=0), None, now=PENDING_TIMEOUT + 1, pending_timeout_ms=PENDING_TIMEOUT)
    assert cp.confirmation_state is ConfirmationState.LOW_CONFIDENCE


# --- guard rails ----------------------------------------------------------------

def test_gait_score_out_of_range_rejected():
    with pytest.raises(ValueError):
        GaitObservation("alice", "ap-3", match_score=1.5, timestamp=0)

def test_login_axis_preserved_alongside_body_axis():
    # the two axes stay independent: PRESENT login can be UNCONFIRMED body
    cp = confirm(_rec(PresenceState.PRESENT), _gait(0.1), now=1000, pending_timeout_ms=PENDING_TIMEOUT)
    assert cp.login_state is PresenceState.PRESENT
    assert cp.confirmation_state is ConfirmationState.UNCONFIRMED
