"""End-to-end demo: login + body fusion, start to finish.

WHY: the tests prove each piece works; this proves they work TOGETHER, and it does so
visibly. It fabricates a handful of network sessions, runs them through the real presence
engine, attaches a (scripted) gait score to each person, and prints the final attendance
verdict. It is the "watch it work" artifact â€” run it in front of someone and the two-axis
idea explains itself.

WHAT it deliberately shows â€” one person per interesting case:
  - alice  : logs in, strong gait      -> CONFIRMED
  - bob    : logs in, weak gait         -> UNCONFIRMED  (the flag: login ok, body doesn't match)
  - carol  : logs in, no walk observed  -> PENDING / LOW_CONFIDENCE (sat out of sensor range)
  - dave   : gait seen, but NEVER logs in -> NO_PRESENCE (gait alone can't manufacture presence)

Gait scores here are SCRIPTED, not from the model â€” so the story is clean and repeatable.
The model's own proof is its training run (chance -> ~100%). This demo is about the fusion.

Run:  PYTHONPATH=src python -m presence_platform.demo
"""

from __future__ import annotations

from presence_platform.core.models import SessionEvent, EventType
from presence_platform.pipeline.presence_engine import PresenceEngine
from presence_platform.pipeline.confirmation import (
    confirm, GaitObservation, ConfirmationState,
)

MIN = 60 * 1000  # one minute in epoch-ms, for readable timestamps

# Emoji-free status labels so it prints cleanly on any terminal.
LABEL = {
    ConfirmationState.CONFIRMED:      "[CONFIRMED]     login + body agree",
    ConfirmationState.LOW_CONFIDENCE: "[LOW-CONF]      present per login, body weak/unseen",
    ConfirmationState.UNCONFIRMED:    "[FLAG]          login ok, gait does NOT match  <-- review",
    ConfirmationState.PENDING:        "[PENDING]       logged in, waiting for a walk-by",
    ConfirmationState.NO_PRESENCE:    "[NO PRESENCE]   no login -> gait alone counts for nothing",
}


def build_events() -> list[SessionEvent]:
    """A few fabricated network sessions. alice/bob/carol log in; dave never does."""
    def ev(user, etype, minute):
        return SessionEvent(
            user_id=user, device_mac="aa:bb:cc:dd:ee:ff", location_id="ap-3",
            event_type=etype, timestamp=minute * MIN, source="freeradius",
        )
    return [
        ev("alice", EventType.START, 0),
        ev("bob",   EventType.START, 0),
        ev("carol", EventType.START, 1),
        # dave: no events at all -> the engine never sees him
    ]


# Scripted gait: what the BFI layer "observed" for each person. None = no walk seen.
GAIT = {
    "alice": 0.94,   # strong match -> CONFIRMED
    "bob":   0.22,   # gait says not-bob -> FLAG
    "carol": None,   # never walked past a sensor -> PENDING/LOW-CONF
    "dave":  0.99,   # perfect gait... but dave never logged in -> must NOT count
}

PENDING_TIMEOUT = 5 * MIN


def main() -> None:
    events = build_events()

    # 1) run the REAL engine over the login events
    engine = PresenceEngine()
    for e in events:
        engine.process(e)
    now = 2 * MIN  # "current time" for the demo snapshot
    engine.finalize(now=now)

    # index active login-visits by user for lookup
    active = {r.user_id: r for r in engine.current_presence()}

    print("=" * 68)
    print("  ATTENDANCE VERDICTS  (login gate x body confirmation)")
    print("=" * 68)

    for user in ["alice", "bob", "carol", "dave"]:
        record = active.get(user)  # None if the person never logged in
        score = GAIT[user]
        gait = (
            GaitObservation(user, "ap-3", match_score=score, timestamp=now)
            if score is not None else None
        )

        cp = confirm(record, gait, now=now, pending_timeout_ms=PENDING_TIMEOUT)

        login_txt = "yes" if record is not None else "NO"
        gait_txt = f"{score:.2f}" if score is not None else "none"
        state = cp.confirmation_state if cp is not None else ConfirmationState.NO_PRESENCE

        print(f"\n  {user:<6}  login={login_txt:<3}  gait={gait_txt:<5}")
        print(f"          -> {LABEL[state]}")

    print("\n" + "=" * 68)
    print("  Note: dave has perfect gait (0.99) but NEVER logged in -> NO PRESENCE.")
    print("  That is the locked rule in action: gait annotates, login gates.")
    print("=" * 68)


if __name__ == "__main__":
    main()
