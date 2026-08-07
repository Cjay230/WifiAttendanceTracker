"""Tests for the presence engine — the hard real-world cases."""

from presence_platform.core.models import EventType, SessionEvent
from presence_platform.pipeline.presence_engine import (
    PresenceEngine,
    PresenceState,
    build_presence,
)

MIN = 60 * 1000  # one minute in ms


def ev(user, loc, typ, minute):
    return SessionEvent(
        user_id=user, device_mac="mac-" + user, location_id=loc,
        event_type=typ, timestamp=minute * MIN, source="test",
    )


def test_clean_start_stop_is_one_visit():
    events = [ev("rita", "F3", EventType.START, 0), ev("rita", "F3", EventType.STOP, 60)]
    eng = build_presence(events)
    assert len(eng.completed_visits()) == 1
    visit = eng.completed_visits()[0]
    assert visit.state == PresenceState.LEFT
    assert visit.duration_ms == 60 * MIN


def test_missing_stop_times_out_to_left():
    # rita never sends STOP; a later event (sami) advances the clock past left_timeout.
    events = [ev("rita", "F3", EventType.START, 0), ev("sami", "F3", EventType.START, 30)]
    eng = build_presence(events)
    left_users = [r.user_id for r in eng.completed_visits() if r.state == PresenceState.LEFT]
    present_users = [r.user_id for r in eng.current_presence()]
    assert "rita" in left_users       # timed out
    assert "sami" in present_users     # still here


def test_interim_updates_keep_single_visit():
    events = [ev("rita", "F3", EventType.START, 0)]
    for m in range(4, 41, 4):
        events.append(ev("rita", "F3", EventType.UPDATE, m))
    events.append(ev("rita", "F3", EventType.STOP, 40))
    eng = build_presence(events)
    assert len(eng.completed_visits()) == 1
    assert eng.completed_visits()[0].duration_ms == 40 * MIN


def test_idle_state_after_quiet_period():
    eng = PresenceEngine()
    eng.process(ev("rita", "F3", EventType.START, 0))
    eng.process(ev("bob", "F3", EventType.START, 7))  # advances clock; rita quiet 7 min
    rita = [r for r in eng.current_presence() if r.user_id == "rita"][0]
    assert rita.state == PresenceState.IDLE


def test_two_locations_tracked_separately():
    # same user on two floors = two separate visits (movement handled later in Phase 3)
    events = [ev("rita", "F3", EventType.START, 0), ev("rita", "F4", EventType.START, 1)]
    eng = build_presence(events)
    locs = {r.location_id for r in eng.all_records()}
    assert locs == {"F3", "F4"}


def test_reconnect_within_grace_merges_into_one_visit():
    # STOP at minute 10, back within a minute (< reconnect_grace_ms default of 2 min):
    # same visit, not two.
    events = [
        ev("rita", "F3", EventType.START, 0),
        ev("rita", "F3", EventType.STOP, 10),
        ev("rita", "F3", EventType.START, 11),
        ev("rita", "F3", EventType.STOP, 20),
    ]
    eng = build_presence(events)
    assert len(eng.completed_visits()) == 1
    visit = eng.completed_visits()[0]
    assert visit.check_in == 0
    assert visit.check_out == 20 * MIN
    assert visit.duration_ms == 20 * MIN


def test_reconnect_outside_grace_starts_new_visit():
    # STOP at minute 10, back 5 minutes later (> reconnect_grace_ms default of 2 min):
    # a genuinely new visit, not a merge.
    events = [
        ev("rita", "F3", EventType.START, 0),
        ev("rita", "F3", EventType.STOP, 10),
        ev("rita", "F3", EventType.START, 15),
        ev("rita", "F3", EventType.STOP, 20),
    ]
    eng = build_presence(events)
    visits = eng.completed_visits()
    assert len(visits) == 2
    assert all(v.ended_reason == "stop" for v in visits)
    durations = sorted(v.duration_ms for v in visits)
    assert durations == [5 * MIN, 10 * MIN]
