"""Run FreeRADIUS accounting data (typically from generate_sessions.py) through the
full pipeline and print presence stats.

WHY: scale-testing means proving the pipeline holds up in volume, and that its answers
make sense at a glance — not just that it doesn't crash. The clean-vs-timed-out split is
the headline number: it's what generate_sessions.py's missing_stop_pct knob is for.

Usage:
    python scripts/scale_test.py data/generated.detail
"""

from __future__ import annotations

import sys
import time

from presence_platform.pipeline.presence_engine import build_presence
from presence_platform.sources.freeradius.source import FreeRADIUSSource


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: scale_test.py <path-to-detail-file>")
        raise SystemExit(1)

    t0 = time.perf_counter()
    events = list(FreeRADIUSSource(sys.argv[1]).stream_sessions())
    events.sort(key=lambda e: e.timestamp)  # engine assumes time order
    parse_s = time.perf_counter() - t0

    t1 = time.perf_counter()
    engine = build_presence(events)
    engine_s = time.perf_counter() - t1

    active = engine.current_presence()
    completed = engine.completed_visits()
    clean = [r for r in completed if r.ended_reason == "stop"]
    timed_out = [r for r in completed if r.ended_reason == "timeout"]

    users = {r.user_id for r in engine.all_records()}
    locations = {r.location_id for r in engine.all_records()}

    print(f"Parsed {len(events)} event(s) in {parse_s:.2f}s, ran engine in {engine_s:.2f}s.")
    print(f"Users: {len(users)}   Locations: {len(locations)}")
    print(f"Visits: {len(engine.all_records())} total   ({len(active)} still active)")
    print(f"Completed visits: {len(completed)}  -  clean STOP: {len(clean)}  timed out: {len(timed_out)}")

    if completed:
        avg_duration_min = sum(r.duration_ms for r in completed) / len(completed) / 60000
        print(f"Average completed visit duration: {avg_duration_min:.1f} min")


if __name__ == "__main__":
    main()
