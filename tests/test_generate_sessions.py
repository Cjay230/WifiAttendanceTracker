"""Tests for the synthetic session generator, exercising the full pipeline:
generator's detail-file output -> FreeRADIUSSource -> PresenceEngine.

WHY: generate()'s workday is stochastic by design (that's the point, for scale
testing), so it isn't asserted on directly here. Instead this builds a small, known
set of records with the generator's own (deterministic) record formatter, covering
exactly the hard cases the generator is meant to produce: a clean visit, a missing
STOP that times out, a reconnect inside the grace window that merges into one visit,
and a long session with interim updates.
"""

from __future__ import annotations

import sys
from pathlib import Path

# generate_sessions.py lives in scripts/, not an installed package -> put it on the
# path directly rather than adding project-wide test config for one module.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from generate_sessions import make_record, write_detail_file  # noqa: E402

from presence_platform.pipeline.presence_engine import PresenceState, build_presence
from presence_platform.sources.freeradius.source import FreeRADIUSSource

MIN = 60  # one minute in seconds -- detail-file Timestamp fields are epoch seconds


def _build_scenario(path: Path) -> None:
    """Hand-picked records covering the engine's hard cases, in one detail file.

    Timeline (all on distinct users so each case is isolated):
      rita  (F3): clean Start/Stop, 0 -> 5 min.
      bob   (F3): Start only at 6 min -- dead phone, must time out later.
      carol (F4): Start 10, Stop 11, Start 11:40 (40s gap, inside the 2-min grace
                  window) -> merges into ONE visit, Stop at 15 min.
      dave  (F5): Start 0, Interim-Updates every 10 min, Stop at 50 min.
      erin  (F3): Start at 60 min -- last event, stays open (present at end).
    """
    records = [
        make_record("rita", "AA:AA:AA:AA:AA:01", "AP-Floor3", "Start", 0, "s-rita-1"),
        make_record("rita", "AA:AA:AA:AA:AA:01", "AP-Floor3", "Stop", 5 * MIN, "s-rita-1", session_time_s=5 * MIN),

        make_record("bob", "AA:AA:AA:AA:AA:02", "AP-Floor3", "Start", 6 * MIN, "s-bob-1"),

        make_record("carol", "AA:AA:AA:AA:AA:03", "AP-Floor4", "Start", 10 * MIN, "s-carol-1"),
        make_record("carol", "AA:AA:AA:AA:AA:03", "AP-Floor4", "Stop", 11 * MIN, "s-carol-1", session_time_s=1 * MIN),
        make_record("carol", "AA:AA:AA:AA:AA:03", "AP-Floor4", "Start", 11 * MIN + 40, "s-carol-2"),
        make_record("carol", "AA:AA:AA:AA:AA:03", "AP-Floor4", "Stop", 15 * MIN, "s-carol-2", session_time_s=3 * MIN + 20),

        make_record("dave", "AA:AA:AA:AA:AA:04", "AP-Floor5", "Start", 0, "s-dave-1"),
        make_record("dave", "AA:AA:AA:AA:AA:04", "AP-Floor5", "Interim-Update", 10 * MIN, "s-dave-1"),
        make_record("dave", "AA:AA:AA:AA:AA:04", "AP-Floor5", "Interim-Update", 20 * MIN, "s-dave-1"),
        make_record("dave", "AA:AA:AA:AA:AA:04", "AP-Floor5", "Interim-Update", 30 * MIN, "s-dave-1"),
        make_record("dave", "AA:AA:AA:AA:AA:04", "AP-Floor5", "Interim-Update", 40 * MIN, "s-dave-1"),
        make_record("dave", "AA:AA:AA:AA:AA:04", "AP-Floor5", "Stop", 50 * MIN, "s-dave-1", session_time_s=50 * MIN),

        make_record("erin", "AA:AA:AA:AA:AA:05", "AP-Floor3", "Start", 60 * MIN, "s-erin-1"),
    ]
    write_detail_file(path, records)


def test_generated_scenario_produces_expected_visits(tmp_path):
    detail_path = tmp_path / "scenario.detail"
    _build_scenario(detail_path)

    events = list(FreeRADIUSSource(detail_path).stream_sessions())
    assert len(events) == 14  # 2 + 1 + 4 + 6 + 1, see _build_scenario
    events.sort(key=lambda e: e.timestamp)  # engine assumes time order, as scale_test.py does

    engine = build_presence(events)
    completed_by_user = {r.user_id: r for r in engine.completed_visits()}

    # rita: clean stop, untouched by anyone else's timeline.
    assert completed_by_user["rita"].ended_reason == "stop"
    assert completed_by_user["rita"].duration_ms == 5 * MIN * 1000

    # bob: dead phone -- no Stop record was ever written, so this must be a timeout.
    assert completed_by_user["bob"].ended_reason == "timeout"

    # carol: STOP + reconnect 40s later (inside the 2-min grace window) must be ONE
    # merged visit, not two -- so exactly one completed record for her, spanning the
    # full 10..15 min window including the reconnect gap.
    assert sum(1 for r in engine.all_records() if r.user_id == "carol") == 1
    assert completed_by_user["carol"].ended_reason == "stop"
    assert completed_by_user["carol"].duration_ms == 5 * MIN * 1000

    # dave: interim updates every 10 min must keep a single 50-min visit alive, not
    # split it or time it out (the 10-min gaps are under the 15-min left_timeout).
    assert completed_by_user["dave"].ended_reason == "stop"
    assert completed_by_user["dave"].duration_ms == 50 * MIN * 1000

    # erin: last event in the stream -- still open, not yet timed out.
    active_by_user = {r.user_id: r for r in engine.current_presence()}
    assert active_by_user["erin"].state == PresenceState.PRESENT

    assert len(engine.completed_visits()) == 4  # rita, bob, carol (merged), dave
    assert len(engine.current_presence()) == 1  # erin
